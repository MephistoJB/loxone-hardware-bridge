"""Update coordinator for Loxone Hardware Bridge."""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LoxoneHardwareApi, LoxoneHardwareError
from .const import (
    CONF_BATTERY_INTERVAL,
    CONF_FAST_POLL_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_BATTERY_INTERVAL,
    DEFAULT_FAST_POLL_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
)
from .models import BridgeData

_LOGGER = logging.getLogger(__name__)


class LoxoneHardwareCoordinator(DataUpdateCoordinator[BridgeData]):
    """Coordinate push events and tiered polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: LoxoneHardwareApi,
        initial_data: BridgeData,
        push_mapping: dict[str, tuple[str, str]],
    ) -> None:
        fast_interval = int(
            entry.options.get(CONF_FAST_POLL_INTERVAL, DEFAULT_FAST_POLL_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=fast_interval),
            always_update=True,
        )
        self.config_entry = entry
        self.api = api
        self.data = initial_data
        self.push_mapping = push_mapping
        self._last_status_monotonic = 0.0
        self._last_battery_monotonic = 0.0

    @property
    def status_interval(self) -> int:
        """Return status/discovery interval in seconds."""
        return int(
            self.config_entry.options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)
        )

    @property
    def battery_interval(self) -> int:
        """Return battery interval in seconds."""
        minutes = int(
            self.config_entry.options.get(
                CONF_BATTERY_INTERVAL, DEFAULT_BATTERY_INTERVAL
            )
        )
        return minutes * 60

    async def _async_update_data(self) -> BridgeData:
        """Run the appropriate polling tiers."""
        now = time.monotonic()
        try:
            current = deepcopy(self.data)
            if now - self._last_status_monotonic >= self.status_interval:
                discovered, push_mapping = await self.api.async_discover()
                self._merge_runtime_values(discovered, current)
                current = discovered
                self.push_mapping = push_mapping
                self._last_status_monotonic = now

            current = await self.api.async_poll_fast(current)

            if now - self._last_battery_monotonic >= self.battery_interval:
                current = await self.api.async_poll_battery(current)
                self._last_battery_monotonic = now
            return current
        except LoxoneHardwareError as err:
            raise UpdateFailed(f"Could not update Loxone hardware: {err}") from err

    @staticmethod
    def _merge_runtime_values(target: BridgeData, source: BridgeData) -> None:
        """Preserve fast values while refreshing device metadata."""
        target.websocket_connected = source.websocket_connected
        target.last_push = source.last_push
        target.last_poll = source.last_poll
        for device_id, target_handle in target.handles.items():
            if source_handle := source.handles.get(device_id):
                target_handle.position = source_handle.position
                target_handle.alarm = source_handle.alarm
                target_handle.push_position_uuid = source_handle.push_position_uuid
                target_handle.push_alarm_uuid = source_handle.push_alarm_uuid

    async def async_apply_push(self, values: dict[str, float]) -> None:
        """Apply relevant WebSocket values immediately."""
        if not self.data:
            return
        updated = deepcopy(self.data)
        changed = False
        for state_uuid, value in values.items():
            mapped = self.push_mapping.get(state_uuid.lower())
            if not mapped:
                continue
            device_id, attribute = mapped
            handle = updated.handles.get(device_id)
            if not handle:
                continue
            new_value: int | bool = (
                round(value) if attribute == "position" else bool(value)
            )
            if getattr(handle, attribute) != new_value:
                setattr(handle, attribute, new_value)
                changed = True
        if changed:
            updated.last_push = datetime.now(timezone.utc)
            self.async_set_updated_data(updated)

    async def async_set_push_connected(self, connected: bool) -> None:
        """Expose WebSocket connection health without affecting HTTP availability."""
        if not self.data or self.data.websocket_connected == connected:
            return
        updated = deepcopy(self.data)
        updated.websocket_connected = connected
        self.async_set_updated_data(updated)
