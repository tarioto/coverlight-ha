"""UI setup: one config entry per room (a speaker plus the lights that should follow it)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_LIGHTS, CONF_MEDIA_PLAYER, CONF_RESTORE_LIGHTS, DOMAIN

CONF_NAME = "name"


def _room_schema(defaults: dict[str, Any], include_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_name:
        fields[vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, ""))] = selector.TextSelector()
    fields[vol.Required(CONF_MEDIA_PLAYER, default=defaults.get(CONF_MEDIA_PLAYER, vol.UNDEFINED))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player"))
    )
    fields[vol.Required(CONF_LIGHTS, default=defaults.get(CONF_LIGHTS, vol.UNDEFINED))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True))
    )
    fields[vol.Optional(CONF_RESTORE_LIGHTS, default=defaults.get(CONF_RESTORE_LIGHTS, True))] = (
        selector.BooleanSelector()
    )
    return vol.Schema(fields)


class CoverlightConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_LIGHTS):
                errors[CONF_LIGHTS] = "no_lights"
            else:
                await self.async_set_unique_id(user_input[CONF_MEDIA_PLAYER])
                self._abort_if_unique_id_configured()
                name = user_input.pop(CONF_NAME, "").strip()
                if not name:
                    state = self.hass.states.get(user_input[CONF_MEDIA_PLAYER])
                    name = state.name if state else user_input[CONF_MEDIA_PLAYER]
                return self.async_create_entry(title=name, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_room_schema(user_input or {}, include_name=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CoverlightOptionsFlow()


class CoverlightOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_LIGHTS):
                errors[CONF_LIGHTS] = "no_lights"
            else:
                return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_room_schema(user_input or current, include_name=False),
            errors=errors,
        )
