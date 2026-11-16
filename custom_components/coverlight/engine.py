"""Per-room sync: watches a media player's artwork and drifts the room's lights through its palette."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import ATTR_ENTITY_PICTURE, STATE_OFF, STATE_PLAYING
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    DEFAULT_BRIGHTNESS,
    DEFAULT_MOTION,
    DRIFT_PERIOD,
    MIN_STEP,
    STEP_PER_LIGHT,
    TRACK_STAGGER,
    TRACK_TRANSITION,
)
from .palette import WARM_WHITE, Swatch, assign_lights, extract_palette, light_target

_LOGGER = logging.getLogger(__name__)


class RoomSync:
    """Drives one room. Created per config entry; idle until `async_start`."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        media_player: str,
        lights: list[str],
        restore_lights: bool,
    ) -> None:
        self.hass = hass
        self.media_player = media_player
        self.lights = lights
        self.restore_lights = restore_lights
        self._scene_id = f"coverlight_{entry_id.lower()}"

        self.enabled = False
        self.brightness = DEFAULT_BRIGHTNESS
        self.motion = DEFAULT_MOTION
        self.palette: list[Swatch] = [WARM_WHITE]
        self._slots = assign_lights(self.palette, len(lights))

        self._artwork: str | None = None
        self._unsub_state: Callable[[], None] | None = None
        self._loop_task: asyncio.Task | None = None
        self._palette_task: asyncio.Task | None = None
        self._listeners: list[Callable[[], None]] = []

    # ---- lifecycle -------------------------------------------------------------------------

    async def async_start(self) -> None:
        if self.enabled:
            return
        self.enabled = True
        if self.restore_lights:
            await self._snapshot()
        self._unsub_state = async_track_state_change_event(
            self.hass, [self.media_player], self._on_media_change
        )
        self._artwork = None
        await self._refresh_palette(turn_on=True)
        self._loop_task = self.hass.async_create_background_task(
            self._drift_loop(), f"coverlight drift {self.media_player}"
        )
        self._notify()

    async def async_stop(self) -> None:
        if not self.enabled:
            return
        self.enabled = False
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        for task in (self._loop_task, self._palette_task):
            if task:
                task.cancel()
        self._loop_task = self._palette_task = None
        if self.restore_lights:
            await self._restore()
        self._notify()

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ---- settings (from the number entities) ------------------------------------------------

    async def async_set_brightness(self, value: float) -> None:
        self.brightness = value
        if self.enabled:
            await self._push_all(transition=1.0)

    async def async_set_motion(self, value: float) -> None:
        self.motion = value  # picked up by the next drift step

    # ---- artwork → palette ------------------------------------------------------------------

    @callback
    def _on_media_change(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        artwork = new.attributes.get(ATTR_ENTITY_PICTURE) if new else None
        if artwork != self._artwork:
            if self._palette_task:
                self._palette_task.cancel()
            self._palette_task = self.hass.async_create_task(self._refresh_palette())

    async def _refresh_palette(self, turn_on: bool = False) -> None:
        state = self.hass.states.get(self.media_player)
        self._artwork = state.attributes.get(ATTR_ENTITY_PICTURE) if state else None
        data = await self._fetch_artwork() if self._artwork else None
        if data is None:
            # Nothing playing (yet): keep the current colors, but light the room when starting.
            if turn_on and self.enabled:
                await self._push_all(transition=TRACK_TRANSITION, turn_on=True, stagger=TRACK_STAGGER)
            return
        palette = await self.hass.async_add_executor_job(extract_palette, data)
        if not self.enabled:
            return
        self.palette = palette
        self._slots = assign_lights(palette, len(self.lights))
        _LOGGER.debug("%s palette: %s, lights: %s", self.media_player, palette, self._slots)
        # Stagger the crossfade so the new palette sweeps through the room in light order.
        await self._push_all(transition=TRACK_TRANSITION, turn_on=turn_on, stagger=TRACK_STAGGER)

    async def _fetch_artwork(self) -> bytes | None:
        # Ask the media player entity directly: no URL, auth token or network round trip.
        component = self.hass.data.get(MEDIA_PLAYER_DOMAIN)
        entity = component.get_entity(self.media_player) if component else None
        if entity is not None:
            try:
                data, _ = await entity.async_get_media_image()
                if data:
                    return data
            except Exception:  # noqa: BLE001 - fall back to the proxy URL below
                _LOGGER.debug("Direct artwork fetch failed for %s", self.media_player, exc_info=True)

        if not self._artwork:
            return None
        url = self._artwork
        if not url.startswith("http"):
            try:
                url = get_url(self.hass, prefer_external=False) + url
            except NoURLAvailableError:
                return None
        try:
            async with async_get_clientsession(self.hass).get(url, timeout=10) as response:
                response.raise_for_status()
                return await response.read()
        except Exception:  # noqa: BLE001 - a missing cover shouldn't break the room
            _LOGGER.warning("Couldn't load artwork for %s", self.media_player, exc_info=True)
            return None

    # ---- lights -----------------------------------------------------------------------------

    async def _drift_loop(self) -> None:
        """Re-target each light every step, staggered so commands trickle out evenly."""
        step = max(MIN_STEP, STEP_PER_LIGHT * len(self.lights))
        gap = step / max(1, len(self.lights))
        while True:
            for rank, light in enumerate(self.lights):
                await asyncio.sleep(gap)
                # Even a one-color palette moves: brightness breathes with motion.
                if self.motion > 0 and self._is_playing():
                    # Aim at where the drift will be when this transition ends.
                    await self._send(light, rank, transition=step, at=time.time() + step)

    def _is_playing(self) -> bool:
        state = self.hass.states.get(self.media_player)
        return state is not None and state.state == STATE_PLAYING

    async def _push_all(self, transition: float, turn_on: bool = False, stagger: float = 0.0) -> None:
        for rank, light in enumerate(self.lights):
            if rank and stagger:
                await asyncio.sleep(stagger)
            await self._send(
                light, rank, transition=transition, at=time.time() + transition, turn_on=turn_on
            )

    async def _send(
        self, light: str, rank: int, transition: float, at: float, turn_on: bool = False
    ) -> None:
        # Only the initial push may switch lights on; after that, a light someone
        # turned off by hand stays off.
        state = self.hass.states.get(light)
        if not turn_on and state is not None and state.state == STATE_OFF:
            return
        target = light_target(
            self.palette, self._slots[rank], rank, at, self.motion / 100, DRIFT_PERIOD
        )
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            "turn_on",
            {
                "entity_id": light,
                "hs_color": [round(target.hue * 360, 1), round(target.saturation * 100, 1)],
                "brightness_pct": max(1, round(self.brightness * target.brightness)),
                "transition": transition,
            },
            blocking=False,
        )

    # ---- restore what the lights looked like before -----------------------------------------

    async def _snapshot(self) -> None:
        try:
            await self.hass.services.async_call(
                "scene",
                "create",
                {"scene_id": self._scene_id, "snapshot_entities": self.lights},
                blocking=True,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Couldn't snapshot %s; lights won't be restored", self.lights, exc_info=True)

    async def _restore(self) -> None:
        scene = f"scene.{self._scene_id}"
        if self.hass.states.get(scene) is None:
            return
        try:
            await self.hass.services.async_call(
                "scene", "turn_on", {"entity_id": scene, "transition": 1.5}, blocking=False
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Couldn't restore %s", self.lights, exc_info=True)
