"""Constants for Loxone Hardware Bridge."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "loxone_hardware"
NAME: Final = "Loxone Hardware Bridge"
MANUFACTURER: Final = "Loxone"

PLATFORMS: Final = ["sensor", "binary_sensor"]

CONF_USE_SSL: Final = "use_ssl"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_ENABLE_PUSH: Final = "enable_push"
CONF_FAST_POLL_INTERVAL: Final = "fast_poll_interval"
CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_BATTERY_INTERVAL: Final = "battery_interval"

DEFAULT_PORT: Final = 80
DEFAULT_SSL_PORT: Final = 443
DEFAULT_USE_SSL: Final = False
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_ENABLE_PUSH: Final = True
DEFAULT_FAST_POLL_INTERVAL: Final = 2
DEFAULT_STATUS_INTERVAL: Final = 30
DEFAULT_BATTERY_INTERVAL: Final = 15

MIN_FAST_POLL_INTERVAL: Final = 1
MAX_FAST_POLL_INTERVAL: Final = 30
MIN_STATUS_INTERVAL: Final = 10
MAX_STATUS_INTERVAL: Final = 300
MIN_BATTERY_INTERVAL: Final = 1
MAX_BATTERY_INTERVAL: Final = 1440

AIR_DEVICE_TYPE_WINDOW_HANDLE: Final = "Fenstergriff Air"
CHANNEL_BATTERY_LOW: Final = "I0"
CHANNEL_BATTERY: Final = "AI0"
CHANNEL_POSITION: Final = "AI2"
CHANNEL_CLOSED: Final = "I2"
CHANNEL_TILTED: Final = "I3"
CHANNEL_ALARM: Final = "I4"

POSITION_CLOSED: Final = 1
POSITION_TILTED: Final = 2
POSITION_OPEN: Final = 3

ATTRIBUTION: Final = "Data provided by the local Loxone Miniserver"
