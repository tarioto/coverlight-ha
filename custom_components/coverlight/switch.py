"""The room's Sync switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started

from .entity import CoverlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([SyncSwitch(entry)])


class SyncSwitch(CoverlightEntity, SwitchEntity, RestoreEntity):
    def __init__(self, entry) -> None:
        super().__init__(entry, "sync")

    @property
    def is_on(self) -> bool:
        return self.room.enabled

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.room.add_listener(self.async_write_ha_state))
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_ON:
            # Wait until the speaker and light integrations are loaded before resuming.
            self.async_on_remove(async_at_started(self.hass, self._async_resume))

    async def _async_resume(self, _hass: HomeAssistant) -> None:
        await self.room.async_start()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.room.async_start()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.room.async_stop()
