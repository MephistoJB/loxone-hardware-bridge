"""Sensor platform for Loxone Hardware Bridge."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LoxoneHardwareConfigEntry
from .const import CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH
from .entity import LoxoneHardwareEntity
from .models import WindowHandle


class LoxonePositionSensor(LoxoneHardwareEntity, SensorEntity):
    """Three-state handle position."""

    _attr_translation_key = "position"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["closed", "tilted", "open", "unknown"]
    _attr_icon = "mdi:window-closed-variant"

    def __init__(self, entry: LoxoneHardwareConfigEntry, device_id: str) -> None:
        super().__init__(entry, device_id, "position")

    @property
    def native_value(self) -> str:
        return self.handle.position_name or "unknown"

    @property
    def icon(self) -> str:
        return {
            "closed": "mdi:window-closed-variant",
            "tilted": "mdi:angle-acute",
            "open": "mdi:window-open-variant",
        }.get(self.native_value, "mdi:window-closed-alert")


class LoxoneHandleSensor(LoxoneHardwareEntity, SensorEntity):
    """A diagnostic sensor belonging to a window handle."""

    def __init__(
        self,
        entry: LoxoneHardwareConfigEntry,
        device_id: str,
        description: SensorEntityDescription,
        value_fn: Callable[[WindowHandle], Any],
        available_when_offline: bool = False,
    ) -> None:
        super().__init__(entry, device_id, description.key)
        self.entity_description = description
        self._value_fn = value_fn
        self._available_when_offline = available_when_offline

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.handle)

    @property
    def available(self) -> bool:
        if self._available_when_offline:
            return self.coordinator.last_update_success
        return super().available


class LoxoneUpdateModeSensor(LoxoneHardwareEntity, SensorEntity):
    """Show whether live handle values arrive through polling or push."""

    _attr_translation_key = "update_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options: ClassVar[list[str]] = ["polled", "hybrid", "pushed"]
    _attr_icon = "mdi:update"

    def __init__(self, entry: LoxoneHardwareConfigEntry, device_id: str) -> None:
        super().__init__(entry, device_id, "update_mode")

    @property
    def _push_connected(self) -> bool:
        return bool(
            self.entry.options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH)
            and self.coordinator.data.websocket_connected
        )

    @property
    def native_value(self) -> str:
        if not self._push_connected:
            return "polled"
        pushed_channels = sum(
            (
                bool(self.handle.push_position_uuid),
                bool(self.handle.push_alarm_uuid),
            )
        )
        if pushed_channels == 2:
            return "pushed"
        if pushed_channels == 1:
            return "hybrid"
        return "polled"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        position_push = self._push_connected and bool(self.handle.push_position_uuid)
        vibration_push = self._push_connected and bool(self.handle.push_alarm_uuid)
        return {
            **super().extra_state_attributes,
            "position_source": "push" if position_push else "polling",
            "vibration_source": "push" if vibration_push else "polling",
            "polling_fallback": True,
            "websocket_connected": self.coordinator.data.websocket_connected,
        }


SENSOR_TYPES: tuple[
    tuple[SensorEntityDescription, Callable[[WindowHandle], Any], bool], ...
] = (
    (
        SensorEntityDescription(
            key="battery",
            translation_key="battery",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        lambda handle: handle.battery,
        False,
    ),
    (
        SensorEntityDescription(
            key="hops",
            translation_key="hops",
            native_unit_of_measurement="hops",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:access-point-network",
        ),
        lambda handle: handle.hops,
        True,
    ),
    (
        SensorEntityDescription(
            key="quality_device",
            translation_key="quality_device",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:signal",
        ),
        lambda handle: handle.quality_device,
        True,
    ),
    (
        SensorEntityDescription(
            key="quality_extension",
            translation_key="quality_extension",
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:signal-distance-variant",
        ),
        lambda handle: handle.quality_extension,
        True,
    ),
    (
        SensorEntityDescription(
            key="last_received",
            translation_key="last_received",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        lambda handle: handle.last_received,
        True,
    ),
)


async def async_setup_entry(
    hass,
    entry: LoxoneHardwareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all sensor entities and add newly discovered devices."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def add_new_devices() -> None:
        new_ids = set(coordinator.data.handles) - known
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[SensorEntity] = []
        for device_id in sorted(new_ids):
            entities.extend(
                (
                    LoxonePositionSensor(entry, device_id),
                    LoxoneUpdateModeSensor(entry, device_id),
                )
            )
            entities.extend(
                LoxoneHandleSensor(entry, device_id, description, value_fn, offline)
                for description, value_fn, offline in SENSOR_TYPES
            )
        async_add_entities(entities)

    add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(add_new_devices))
