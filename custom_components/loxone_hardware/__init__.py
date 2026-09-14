"""Loxone Hardware Bridge integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LoxoneHardwareApi
from .const import (
    CONF_ENABLE_PUSH,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_PUSH,
    DEFAULT_USE_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
)
from .coordinator import LoxoneHardwareCoordinator
from .push import LoxonePushClient


@dataclass(slots=True)
class LoxoneHardwareRuntimeData:
    """Runtime data stored on the config entry."""

    api: LoxoneHardwareApi
    coordinator: LoxoneHardwareCoordinator
    push_client: LoxonePushClient | None
    air_base_device_id: str


type LoxoneHardwareConfigEntry = ConfigEntry[LoxoneHardwareRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: LoxoneHardwareConfigEntry
) -> bool:
    """Set up Loxone Hardware Bridge from a config entry."""
    session = async_get_clientsession(hass)
    api = LoxoneHardwareApi(
        session=session,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        use_ssl=entry.data.get(CONF_USE_SSL, DEFAULT_USE_SSL),
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    initial_data, push_mapping = await api.async_discover()
    coordinator = LoxoneHardwareCoordinator(
        hass, entry, api, initial_data, push_mapping
    )
    await coordinator.async_config_entry_first_refresh()

    registry = dr.async_get(hass)
    air_base_device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={
            (DOMAIN, f"{initial_data.miniserver_serial}:{initial_data.air_base}")
        },
        manufacturer=MANUFACTURER,
        model="Air Base Extension",
        name=f"{initial_data.miniserver_name} Air Base",
        serial_number=initial_data.air_base,
        sw_version=initial_data.air_base_version,
    )

    push_client: LoxonePushClient | None = None
    if entry.options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH):
        push_client = LoxonePushClient(
            api,
            session,
            coordinator.async_apply_push,
            coordinator.async_set_push_connected,
        )
        await push_client.async_start()

    entry.runtime_data = LoxoneHardwareRuntimeData(
        api=api,
        coordinator=coordinator,
        push_client=push_client,
        air_base_device_id=air_base_device.id,
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: LoxoneHardwareConfigEntry
) -> bool:
    """Unload a config entry."""
    if entry.runtime_data.push_client:
        await entry.runtime_data.push_client.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: LoxoneHardwareConfigEntry
) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
