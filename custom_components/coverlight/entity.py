"""Shared base for Coverlight entities: one device per room."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .engine import RoomSync


class CoverlightEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self.room: RoomSync = entry.runtime_data
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Coverlight {entry.title}",
            manufacturer="Coverlight",
            entry_type=DeviceEntryType.SERVICE,
        )
