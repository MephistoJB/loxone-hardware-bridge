"""Base entities for Loxone Hardware Bridge."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoxoneHardwareConfigEntry
from .const import DOMAIN, MANUFACTURER
from .coordinator import LoxoneHardwareCoordinator
from .models import WindowHandle


class LoxoneHardwareEntity(CoordinatorEntity[LoxoneHardwareCoordinator]):
    """Base class for a Window Handle Air entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: LoxoneHardwareConfigEntry,
        device_id: str,
        key: str,
    ) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self.entry = entry
        self.device_id = device_id
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{device_id}_{key}"
        handle = self.handle
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.unique_id}:{handle.serial}")},
            manufacturer=MANUFACTURER,
            model="Window Handle Air",
            name=handle.name,
            serial_number=handle.serial,
            suggested_area=handle.room,
            sw_version=handle.firmware,
            hw_version=handle.hardware_version,
            via_device_id=entry.runtime_data.air_base_device_id,
            configuration_url=entry.runtime_data.api.base_url,
        )

    @property
    def handle(self) -> WindowHandle:
        """Return current handle data."""
        return self.coordinator.data.handles[self.device_id]

    @property
    def available(self) -> bool:
        """Return availability based on HTTP coordinator and Air status."""
        return super().available and self.handle.online

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        """Expose update source diagnostics."""
        return {
            "hardware_address": self.handle.address_prefix,
            "installation": self.handle.installation,
            "push_available": bool(
                self.handle.push_position_uuid or self.handle.push_alarm_uuid
            ),
        }
