"""Coverlight: room lights that take their colors from what the speaker is playing."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_LIGHTS, CONF_MEDIA_PLAYER, CONF_RESTORE_LIGHTS
from .engine import RoomSync

PLATFORMS = [Platform.SWITCH, Platform.NUMBER]

type CoverlightConfigEntry = ConfigEntry[RoomSync]


async def async_setup_entry(hass: HomeAssistant, entry: CoverlightConfigEntry) -> bool:
    settings = {**entry.data, **entry.options}
    entry.runtime_data = RoomSync(
        hass,
        entry.entry_id,
        media_player=settings[CONF_MEDIA_PLAYER],
        lights=list(settings[CONF_LIGHTS]),
        restore_lights=settings.get(CONF_RESTORE_LIGHTS, True),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CoverlightConfigEntry) -> bool:
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: CoverlightConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
