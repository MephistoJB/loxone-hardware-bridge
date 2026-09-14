"""Local HTTP API client for physical Loxone hardware."""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from aiohttp import BasicAuth, ClientError, ClientResponseError, ClientSession

from .const import (
    AIR_DEVICE_TYPE_WINDOW_HANDLE,
    CHANNEL_ALARM,
    CHANNEL_BATTERY,
    CHANNEL_BATTERY_LOW,
    CHANNEL_POSITION,
)
from .models import BridgeData, WindowHandle

_LOGGER = logging.getLogger(__name__)


class LoxoneHardwareError(Exception):
    """Base error for the Loxone hardware API."""


class LoxoneAuthenticationError(LoxoneHardwareError):
    """Raised when authentication fails."""


class LoxoneConnectionError(LoxoneHardwareError):
    """Raised when the Miniserver cannot be reached."""


class LoxoneNoDevicesError(LoxoneHardwareError):
    """Raised when no supported devices are found."""


def parse_enum_devices(value: str) -> tuple[str, str]:
    """Extract Miniserver serial and Air Base address from enumdev."""
    miniserver = re.search(r"\(([0-9A-Fa-f]{12})\)", value)
    air_base = re.search(r"[0-9A-Fa-f]{12}\.([0-9A-Fa-f]{8})", value)
    if not miniserver or not air_base:
        raise LoxoneHardwareError("Could not identify Miniserver and Air Base")
    return miniserver.group(1).upper(), air_base.group(1).upper()


def parse_input_names(value: str) -> dict[str, str]:
    """Return physical input address to configured display-name mapping."""
    result: dict[str, str] = {}
    pattern = re.compile(
        r"(?:^|,\s*)(.*?)\s+\(([0-9A-Fa-f]{8}\.[0-9A-Fa-f]{6}\.(?:AI|I)\d+),"
    )
    for match in pattern.finditer(value):
        result[match.group(2).upper()] = match.group(1).strip()
    return result


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group()) if match else None


def _as_bool(value: str | None) -> bool | None:
    number = _as_int(value)
    return bool(number) if number is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def parse_status_xml(
    xml: str, miniserver_serial: str, air_base_hint: str
) -> BridgeData:
    """Parse Loxone /data/status XML."""
    root = ET.fromstring(xml)
    miniserver = root.find(".//Miniserver")
    extension = root.find(".//Extension[@Type='Air Base']")
    miniserver_name = (
        miniserver.attrib.get("Name", "Loxone Miniserver")
        if miniserver is not None
        else "Loxone Miniserver"
    )
    miniserver_version = (
        miniserver.attrib.get("Version") if miniserver is not None else None
    )
    air_base = air_base_hint
    air_base_version = None
    if extension is not None:
        air_base = extension.attrib.get("Serial", air_base_hint).upper()
        air_base_version = extension.attrib.get("Version")

    data = BridgeData(
        miniserver_serial=miniserver_serial,
        miniserver_name=miniserver_name,
        miniserver_version=miniserver_version,
        air_base=air_base,
        air_base_version=air_base_version,
    )
    for element in root.findall(".//AirDevice"):
        if element.attrib.get("Type") != AIR_DEVICE_TYPE_WINDOW_HANDLE:
            continue
        serial = element.attrib.get("Serial", "").upper()
        if not serial:
            continue
        device_id = "".join(serial.split(":")[-3:])
        data.handles[device_id] = WindowHandle(
            device_id=device_id,
            serial=serial,
            name=element.attrib.get("Name") or f"Window Handle {device_id}",
            room=element.attrib.get("Place") or None,
            installation=element.attrib.get("Inst") or None,
            air_base=air_base,
            online=element.attrib.get("Online", "false").lower() == "true",
            battery=_as_int(element.attrib.get("Battery")),
            battery_low=(
                element.attrib.get("BattWeak", "false").lower() == "true"
                if "BattWeak" in element.attrib
                else None
            ),
            last_received=_parse_datetime(element.attrib.get("LastReceived")),
            firmware=element.attrib.get("Version"),
            hardware_version=element.attrib.get("HwVersion"),
            hops=_as_int(element.attrib.get("Hops")),
            quality_extension=_as_int(element.attrib.get("QualityExt")),
            quality_device=_as_int(element.attrib.get("QualityDev")),
            extra={
                key: value
                for key, value in element.attrib.items()
                if key
                in {
                    "Code",
                    "IP",
                    "TimeDiff",
                    "MinVersion",
                    "IsDeviceAlwaysActive",
                    "BatTooWeakForUpdate",
                }
            },
        )
    return data


def map_push_uuids(
    data: BridgeData, input_names: dict[str, str], structure: dict[str, Any]
) -> dict[str, tuple[str, str]]:
    """Map LoxAPP state UUIDs to physical device attributes."""
    controls_by_name: dict[str, list[dict[str, Any]]] = {}
    for control in structure.get("controls", {}).values():
        name = str(control.get("name", "")).strip().casefold()
        if name:
            controls_by_name.setdefault(name, []).append(control)

    mapping: dict[str, tuple[str, str]] = {}
    for handle in data.handles.values():
        for channel, attribute in (
            (CHANNEL_POSITION, "position"),
            (CHANNEL_ALARM, "alarm"),
        ):
            address = f"{handle.address_prefix}.{channel}".upper()
            configured_name = input_names.get(address)
            expected_names = {
                f"{handle.name}_{'Position' if attribute == 'position' else 'Alarm'}".casefold(),
                f"{handle.name} {'Position' if attribute == 'position' else 'Alarm'}".casefold(),
            }
            if configured_name:
                expected_names.add(configured_name.casefold())
            matches = [
                control
                for name in expected_names
                for control in controls_by_name.get(name, [])
                if str(control.get("type", "")).startswith("InfoOnly")
            ]
            if len(matches) != 1:
                continue
            states = matches[0].get("states") or {}
            state_uuid = states.get("value") or states.get("active")
            if not state_uuid and len(states) == 1:
                state_uuid = next(iter(states.values()))
            if not state_uuid:
                continue
            state_uuid = str(state_uuid).lower()
            mapping[state_uuid] = (handle.device_id, attribute)
            if attribute == "position":
                handle.push_position_uuid = state_uuid
            else:
                handle.push_alarm_uuid = state_uuid
    return mapping


class LoxoneHardwareApi:
    """Read physical device information from a local Loxone Miniserver."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool,
        verify_ssl: bool,
    ) -> None:
        self.session = session
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.verify_ssl = verify_ssl
        scheme = "https" if use_ssl else "http"
        default_port = 443 if use_ssl else 80
        port_part = "" if port == default_port else f":{port}"
        self.base_url = f"{scheme}://{host}{port_part}"
        self.auth = BasicAuth(username, password)
        self.miniserver_serial: str | None = None
        self.air_base: str | None = None
        self.input_names: dict[str, str] = {}
        self.structure: dict[str, Any] = {}

    async def _request_json(self, path: str) -> dict[str, Any]:
        try:
            async with asyncio.timeout(15):
                response = await self.session.get(
                    f"{self.base_url}/{path.lstrip('/')}",
                    auth=self.auth,
                    ssl=self.verify_ssl if self.use_ssl else None,
                )
                if response.status == 401:
                    raise LoxoneAuthenticationError("Invalid username or password")
                response.raise_for_status()
                return await response.json(content_type=None)
        except LoxoneAuthenticationError:
            raise
        except (TimeoutError, ClientError, ValueError) as err:
            raise LoxoneConnectionError(str(err)) from err

    async def _request_text(self, path: str) -> str:
        try:
            async with asyncio.timeout(15):
                response = await self.session.get(
                    f"{self.base_url}/{path.lstrip('/')}",
                    auth=self.auth,
                    ssl=self.verify_ssl if self.use_ssl else None,
                )
                if response.status == 401:
                    raise LoxoneAuthenticationError("Invalid username or password")
                response.raise_for_status()
                return await response.text()
        except LoxoneAuthenticationError:
            raise
        except (TimeoutError, ClientResponseError, ClientError) as err:
            raise LoxoneConnectionError(str(err)) from err

    @staticmethod
    def _ll_value(payload: dict[str, Any]) -> Any:
        ll = payload.get("LL") or {}
        code = str(ll.get("Code", ll.get("code", "")))
        if code != "200":
            raise LoxoneHardwareError(f"Loxone returned code {code}")
        return ll.get("value")

    async def async_validate(self) -> BridgeData:
        """Validate credentials and discover supported devices."""
        enum_payload = await self._request_json("jdev/sps/enumdev")
        serial, air_base = parse_enum_devices(str(self._ll_value(enum_payload)))
        self.miniserver_serial = serial
        self.air_base = air_base
        data = parse_status_xml(
            await self._request_text("data/status"), serial, air_base
        )
        if not data.handles:
            raise LoxoneNoDevicesError("No Loxone Window Handle Air devices found")
        return data

    async def async_discover(self) -> tuple[BridgeData, dict[str, tuple[str, str]]]:
        """Discover devices and map optional push state UUIDs."""
        data = await self.async_validate()
        enum_inputs, structure = await asyncio.gather(
            self._request_json("jdev/sps/enumin"),
            self._request_json("data/LoxAPP3.json"),
        )
        self.input_names = parse_input_names(str(self._ll_value(enum_inputs)))
        self.structure = structure
        mapping = map_push_uuids(data, self.input_names, structure)
        return data, mapping

    async def async_status(self) -> BridgeData:
        """Refresh status and device metadata."""
        if not self.miniserver_serial or not self.air_base:
            return await self.async_validate()
        return parse_status_xml(
            await self._request_text("data/status"),
            self.miniserver_serial,
            self.air_base,
        )

    async def async_read_channel(self, handle: WindowHandle, channel: str) -> str:
        """Read one physical hardware channel."""
        address = quote(f"{handle.address_prefix}.{channel}", safe=".")
        return str(self._ll_value(await self._request_json(f"jdev/sps/io/{address}")))

    async def async_poll_fast(self, data: BridgeData) -> BridgeData:
        """Poll position and vibration for all known handles."""
        updated = deepcopy(data)

        async def read(handle: WindowHandle) -> None:
            try:
                position, alarm = await asyncio.gather(
                    self.async_read_channel(handle, CHANNEL_POSITION),
                    self.async_read_channel(handle, CHANNEL_ALARM),
                )
                handle.position = _as_int(position)
                handle.alarm = _as_bool(alarm)
            except LoxoneHardwareError as err:
                _LOGGER.debug("Fast poll failed for %s: %s", handle.name, err)

        await asyncio.gather(*(read(handle) for handle in updated.handles.values()))
        updated.last_poll = datetime.now().astimezone()
        return updated

    async def async_poll_battery(self, data: BridgeData) -> BridgeData:
        """Poll battery capacity and low-battery input."""
        updated = deepcopy(data)

        async def read(handle: WindowHandle) -> None:
            try:
                battery, low = await asyncio.gather(
                    self.async_read_channel(handle, CHANNEL_BATTERY),
                    self.async_read_channel(handle, CHANNEL_BATTERY_LOW),
                )
                handle.battery = _as_int(battery)
                handle.battery_low = _as_bool(low)
            except LoxoneHardwareError as err:
                _LOGGER.debug("Battery poll failed for %s: %s", handle.name, err)

        await asyncio.gather(*(read(handle) for handle in updated.handles.values()))
        return updated
