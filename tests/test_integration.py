import asyncio
import io
import time
from unittest.mock import patch

from PIL import Image
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.coverlight.const import DOMAIN, TRACK_STAGGER

SPEAKER = "media_player.office"
LIGHTS = ["light.left", "light.right"]


def _cover(color):
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), color).save(buffer, "PNG")
    return buffer.getvalue()


COVERS = {"/art/red": _cover((230, 20, 20)), "/art/green": _cover((20, 220, 40))}


async def _fake_fetch(self):
    return COVERS.get(self._artwork)


def _hue(call):
    return call.data["hs_color"][0]


async def _setup_room(hass: HomeAssistant):
    hass.states.async_set(SPEAKER, "playing", {"entity_picture": "/art/red", "friendly_name": "Office"})
    for light in LIGHTS:
        hass.states.async_set(light, "on")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"media_player": SPEAKER, "lights": LIGHTS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Office"
    await hass.async_block_till_done()
    return result["result"]


async def test_room_follows_artwork(hass: HomeAssistant):
    with patch("custom_components.coverlight.engine.RoomSync._fetch_artwork", _fake_fetch):
        entry = await _setup_room(hass)
        # Mock after setup: loading the real light integration replaces earlier mocks.
        turn_on = async_mock_service(hass, "light", "turn_on")
        scene_create = async_mock_service(hass, "scene", "create")
        scene_on = async_mock_service(hass, "scene", "turn_on")
        assert hass.states.get("switch.coverlight_office_sync").state == "off"
        assert hass.states.get("number.coverlight_office_brightness").state == "80"
        assert not turn_on

        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.coverlight_office_sync"}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get("switch.coverlight_office_sync").state == "on"
        assert scene_create[0].data["snapshot_entities"] == LIGHTS
        assert {c.data["entity_id"] for c in turn_on} == set(LIGHTS)
        assert all(_hue(c) < 10 or _hue(c) > 350 for c in turn_on)  # red
        # 50 % motion breathes at most 7.5 % below the slider.
        assert all(74 <= c.data["brightness_pct"] <= 80 for c in turn_on)

        # New track → crossfade to the new cover's palette.
        turn_on.clear()
        sent_at = []
        unsub = hass.bus.async_listen("call_service", lambda _: sent_at.append(time.monotonic()))
        hass.states.async_set(SPEAKER, "playing", {"entity_picture": "/art/green", "friendly_name": "Office"})
        await hass.async_block_till_done()
        unsub()
        assert len(turn_on) == 2
        assert sent_at[-1] - sent_at[0] >= TRACK_STAGGER * 0.9  # lights sweep, not all at once
        assert all(110 < _hue(c) < 140 for c in turn_on)
        assert all(c.data["transition"] == 2.0 for c in turn_on)

        # Brightness slider pushes immediately.
        turn_on.clear()
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": "number.coverlight_office_brightness", "value": 40}, blocking=True,
        )
        assert len(turn_on) == 2
        assert all(37 <= c.data["brightness_pct"] <= 40 for c in turn_on)

        # Off → restore the snapshot.
        hass.states.async_set(f"scene.coverlight_{entry.entry_id.lower()}", "scening")
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": "switch.coverlight_office_sync"}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get("switch.coverlight_office_sync").state == "off"
        assert len(scene_on) == 1

        # Stopped rooms ignore track changes.
        turn_on.clear()
        hass.states.async_set(SPEAKER, "playing", {"entity_picture": "/art/red"})
        await hass.async_block_till_done()
        assert not turn_on


async def test_drift_skips_lights_turned_off_and_pauses(hass: HomeAssistant):
    two_tone = io.BytesIO()
    image = Image.new("RGB", (100, 100), (230, 20, 20))
    image.paste((20, 40, 230), (50, 0, 100, 100))
    image.save(two_tone, "PNG")
    COVERS["/art/two"] = two_tone.getvalue()

    with (
        patch("custom_components.coverlight.engine.RoomSync._fetch_artwork", _fake_fetch),
        patch("custom_components.coverlight.engine.MIN_STEP", 0.05),
        patch("custom_components.coverlight.engine.STEP_PER_LIGHT", 0.01),
    ):
        await _setup_room(hass)
        turn_on = async_mock_service(hass, "light", "turn_on")
        async_mock_service(hass, "scene", "create")
        hass.states.async_set(SPEAKER, "playing", {"entity_picture": "/art/two"})
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.coverlight_office_sync"}, blocking=True
        )
        hass.states.async_set("light.right", "off")  # someone switched it off by hand
        turn_on.clear()
        await asyncio.sleep(0.3)
        drifted = {c.data["entity_id"] for c in turn_on}
        assert drifted == {"light.left"}
        assert all(c.data["transition"] == 0.05 for c in turn_on)

        hass.states.async_set(SPEAKER, "paused", {"entity_picture": "/art/two"})
        await asyncio.sleep(0.06)
        turn_on.clear()
        await asyncio.sleep(0.3)
        assert not turn_on

        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": "switch.coverlight_office_sync"}, blocking=True
        )


async def test_same_speaker_twice_is_rejected(hass: HomeAssistant):
    await _setup_room(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"media_player": SPEAKER, "lights": ["light.left"]}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_artwork_comes_from_the_media_player_entity(hass: HomeAssistant):
    """Unpatched path: bytes come straight from MediaPlayerEntity.async_get_media_image."""
    entry = await _setup_room(hass)
    room = entry.runtime_data
    component = hass.data["media_player"]

    class FakePlayer:
        async def async_get_media_image(self):
            return COVERS["/art/green"], "image/png"

    with patch.object(component, "get_entity", return_value=FakePlayer()):
        assert await room._fetch_artwork() == COVERS["/art/green"]
