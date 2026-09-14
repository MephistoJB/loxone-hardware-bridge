"""Binary sensor platform for Loxone Hardware Bridge."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoxoneHardwareConfigEntry
from .const import DOMAIN, MANUFACTURER
from .entity import LoxoneHardwareEntity


class LoxoneWindowSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Derived Home Assistant window entity."""

    _attr_translation_key = "window"
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, entry: LoxoneHardwareConfigEntry, device_id: str) -> None:
        super().__init__(entry, device_id, "window")

    @property
    def is_on(self) -> bool | None:
        if self.handle.position is None:
            return None
        return self.handle.position != 1


class LoxoneVibrationSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Raw vibration/alarm input."""

    _attr_translation_key = "vibration"
    _attr_device_class = BinarySensorDeviceClass.VIBRATION

    def __init__(self, entry: LoxoneHardwareConfigEntry, device_id: str) -> None:
        super().__init__(entry, device_id, "vibration")

    @property
    def is_on(self) -> bool | None:
        return self.handle.alarm


class LoxoneBatteryLowSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Raw low-battery input."""

    _attr_translation_key = "battery_low"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: LoxoneHardwareConfigEntry, device_id: str) -> None:
        super().__init__(entry, device_id, "battery_low")

    @property
    def is_on(self) -> bool | None:
        return self.handle.battery_low


class LoxoneOnlineSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Physical Air-device availability."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: LoxoneHardwareConfigEntry, device_id: str) -> None:
        super().__init__(entry, device_id, "online")

    @property
    def is_on(self) -> bool:
        return self.handle.online

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class LoxonePushConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    """WebSocket health sensor attached to the Air Base device."""

    _attr_has_entity_name = True
    _attr_translation_key = "push_connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: LoxoneHardwareConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        data = self.coordinator.data
        self._attr_unique_id = f"{entry.unique_id}_push_connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{data.miniserver_serial}:{data.air_base}")},
            manufacturer=MANUFACTURER,
            model="Air Base Extension",
            name=f"{data.miniserver_name} Air Base",
            serial_number=data.air_base,
            sw_version=data.air_base_version,
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.websocket_connected


async def async_setup_entry(
    hass,
    entry: LoxoneHardwareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors and add newly discovered devices."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def add_new_devices() -> None:
        new_ids = set(coordinator.data.handles) - known
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[BinarySensorEntity] = []
        for device_id in sorted(new_ids):
            entities.extend(
                (
                    LoxoneWindowSensor(entry, device_id),
                    LoxoneVibrationSensor(entry, device_id),
                    LoxoneBatteryLowSensor(entry, device_id),
                    LoxoneOnlineSensor(entry, device_id),
                )
            )
        async_add_entities(entities)

    add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(add_new_devices))
    async_add_entities([LoxonePushConnectionSensor(entry)])
