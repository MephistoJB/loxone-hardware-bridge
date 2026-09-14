"""Data models for Loxone Hardware Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class WindowHandle:
    """Represent one physical Loxone Window Handle Air."""

    device_id: str
    serial: str
    name: str
    room: str | None
    installation: str | None
    air_base: str
    online: bool = False
    position: int | None = None
    alarm: bool | None = None
    battery: int | None = None
    battery_low: bool | None = None
    last_received: datetime | None = None
    firmware: str | None = None
    hardware_version: str | None = None
    hops: int | None = None
    quality_extension: int | None = None
    quality_device: int | None = None
    push_position_uuid: str | None = None
    push_alarm_uuid: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def address_prefix(self) -> str:
        """Return the hardware input address prefix."""
        return f"{self.air_base}.{self.device_id}"

    @property
    def position_name(self) -> str | None:
        """Return the translated raw position name."""
        return {1: "closed", 2: "tilted", 3: "open"}.get(self.position)


@dataclass(slots=True)
class BridgeData:
    """Current bridge data."""

    miniserver_serial: str
    miniserver_name: str
    miniserver_version: str | None
    air_base: str
    air_base_version: str | None
    handles: dict[str, WindowHandle] = field(default_factory=dict)
    websocket_connected: bool = False
    last_push: datetime | None = None
    last_poll: datetime | None = None
