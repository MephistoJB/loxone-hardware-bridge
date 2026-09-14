"""Config flow for Loxone Hardware Bridge."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    LoxoneAuthenticationError,
    LoxoneConnectionError,
    LoxoneHardwareApi,
    LoxoneNoDevicesError,
)
from .const import (
    CONF_BATTERY_INTERVAL,
    CONF_ENABLE_PUSH,
    CONF_FAST_POLL_INTERVAL,
    CONF_STATUS_INTERVAL,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_BATTERY_INTERVAL,
    DEFAULT_ENABLE_PUSH,
    DEFAULT_FAST_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_STATUS_INTERVAL,
    DEFAULT_USE_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MAX_BATTERY_INTERVAL,
    MAX_FAST_POLL_INTERVAL,
    MAX_STATUS_INTERVAL,
    MIN_BATTERY_INTERVAL,
    MIN_FAST_POLL_INTERVAL,
    MIN_STATUS_INTERVAL,
)


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, "192.168.1.45")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_USE_SSL, default=defaults.get(CONF_USE_SSL, DEFAULT_USE_SSL)
            ): BooleanSelector(),
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): BooleanSelector(),
        }
    )


async def _validate_input(hass, user_input: dict[str, Any]):
    api = LoxoneHardwareApi(
        session=async_get_clientsession(hass),
        host=user_input[CONF_HOST],
        port=int(user_input[CONF_PORT]),
        username=user_input[CONF_USERNAME],
        password=user_input[CONF_PASSWORD],
        use_ssl=user_input[CONF_USE_SSL],
        verify_ssl=user_input[CONF_VERIFY_SSL],
    )
    return await api.async_validate()


class LoxoneHardwareConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Loxone Hardware Bridge config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = await _validate_input(self.hass, user_input)
            except LoxoneAuthenticationError:
                errors["base"] = "invalid_auth"
            except LoxoneNoDevicesError:
                errors["base"] = "no_devices"
            except LoxoneConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(data.miniserver_serial)
                self._abort_if_unique_id_configured()
                normalized = dict(user_input)
                normalized[CONF_PORT] = int(normalized[CONF_PORT])
                return self.async_create_entry(
                    title=f"Loxone Hardware Bridge ({user_input[CONF_HOST]})",
                    data=normalized,
                )
        return self.async_show_form(
            step_id="user", data_schema=_connection_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = await _validate_input(self.hass, user_input)
            except LoxoneAuthenticationError:
                errors["base"] = "invalid_auth"
            except LoxoneNoDevicesError:
                errors["base"] = "no_devices"
            except LoxoneConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(data.miniserver_serial)
                self._abort_if_unique_id_mismatch()
                normalized = dict(user_input)
                normalized[CONF_PORT] = int(normalized[CONF_PORT])
                return self.async_update_reload_and_abort(
                    entry, data_updates=normalized
                )
        defaults = dict(entry.data)
        defaults.pop(CONF_PASSWORD, None)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(defaults),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return LoxoneHardwareOptionsFlow()


class LoxoneHardwareOptionsFlow(OptionsFlow):
    """Handle update mechanism options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_PUSH,
                    default=options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH),
                ): BooleanSelector(),
                vol.Required(
                    CONF_FAST_POLL_INTERVAL,
                    default=options.get(
                        CONF_FAST_POLL_INTERVAL, DEFAULT_FAST_POLL_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_FAST_POLL_INTERVAL,
                        max=MAX_FAST_POLL_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Required(
                    CONF_STATUS_INTERVAL,
                    default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_STATUS_INTERVAL,
                        max=MAX_STATUS_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Required(
                    CONF_BATTERY_INTERVAL,
                    default=options.get(
                        CONF_BATTERY_INTERVAL, DEFAULT_BATTERY_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_BATTERY_INTERVAL,
                        max=MAX_BATTERY_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
