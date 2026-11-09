"""Brightness and Motion sliders for a room."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DEFAULT_BRIGHTNESS, DEFAULT_MOTION
from .entity import CoverlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([BrightnessNumber(entry), MotionNumber(entry)])


class _PercentNumber(CoverlightEntity, RestoreNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG
    _default: float

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_number_data()
        value = last.native_value if last and last.native_value is not None else self._default
        await self._apply(value)

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        await self._apply(value)
        self.async_write_ha_state()

    async def _apply(self, value: float) -> None:
        raise NotImplementedError


class BrightnessNumber(_PercentNumber):
    _attr_native_min_value = 1
    _default = DEFAULT_BRIGHTNESS

    def __init__(self, entry) -> None:
        super().__init__(entry, "brightness")
        self._value = self._default

    async def _apply(self, value: float) -> None:
        self._value = value
        await self.room.async_set_brightness(value)


class MotionNumber(_PercentNumber):
    _default = DEFAULT_MOTION

    def __init__(self, entry) -> None:
        super().__init__(entry, "motion")
        self._value = self._default

    async def _apply(self, value: float) -> None:
        self._value = value
        await self.room.async_set_motion(value)
