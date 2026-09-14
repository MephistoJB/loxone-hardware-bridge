"""Encrypted Loxone WebSocket push client."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .api import LoxoneHardwareApi

_LOGGER = logging.getLogger(__name__)

MESSAGE_TEXT = 0
MESSAGE_VALUE_STATES = 2
MESSAGE_TEXT_STATES = 3
MESSAGE_OUT_OF_SERVICE = 5
MESSAGE_KEEPALIVE = 6
RECONNECT_AFTER_SECONDS = 12 * 60 * 60


class LoxonePushError(Exception):
    """Raised for a WebSocket protocol or authentication error."""


@dataclass(slots=True)
class _Message:
    message_type: int
    payload: bytes | None


def loxone_uuid_from_bytes(value: bytes) -> str:
    """Convert a 16-byte Loxone UUID into its structure-file representation."""
    if len(value) != 16:
        raise ValueError("A Loxone UUID must contain 16 bytes")
    first, second, third = struct.unpack("<IHH", value[:8])
    return (
        f"{first:08x}-{second:04x}-{third:04x}-{value[8:10].hex()}{value[10:16].hex()}"
    )


def parse_value_states(payload: bytes) -> dict[str, float]:
    """Parse a Loxone value-state event table."""
    result: dict[str, float] = {}
    for offset in range(0, len(payload) - 23, 24):
        state_uuid = loxone_uuid_from_bytes(payload[offset : offset + 16])
        result[state_uuid] = struct.unpack("<d", payload[offset + 16 : offset + 24])[0]
    return result


class LoxonePushClient:
    """Maintain an authenticated local Loxone WebSocket connection."""

    def __init__(
        self,
        api: LoxoneHardwareApi,
        session: ClientSession,
        value_callback: Callable[[dict[str, float]], Awaitable[None]],
        connection_callback: Callable[[bool], Awaitable[None]],
    ) -> None:
        self.api = api
        self.session = session
        self.value_callback = value_callback
        self.connection_callback = connection_callback
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._ws: ClientWebSocketResponse | None = None
        self._aes_key = b""
        self._iv = b""
        self._salt = ""
        self._salt_created = 0.0
        self._salt_uses = 0
        self.connected = False

    async def async_start(self) -> None:
        """Start the reconnecting push listener."""
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="loxone_hardware_websocket")

    async def async_stop(self) -> None:
        """Stop the listener and close its socket."""
        self._stop.set()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        await self._set_connected(False)

    async def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        await self.connection_callback(connected)

    async def _run(self) -> None:
        delay = 1
        while not self._stop.is_set():
            try:
                await self._run_connection()
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect boundary
                _LOGGER.warning("Loxone push connection failed: %s", err)
            finally:
                await self._set_connected(False)
                if self._ws and not self._ws.closed:
                    await self._ws.close()
                self._ws = None
            if self._stop.is_set():
                return
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 30)

    async def _run_connection(self) -> None:
        public_key = await self._get_public_key()
        self._aes_key = secrets.token_bytes(32)
        self._iv = secrets.token_bytes(16)
        self._salt = ""
        self._salt_uses = 0
        session_key = public_key.encrypt(
            f"{self._aes_key.hex()}:{self._iv.hex()}".encode(),
            asymmetric_padding.PKCS1v15(),
        )
        websocket_scheme = "wss" if self.api.use_ssl else "ws"
        default_port = 443 if self.api.use_ssl else 80
        port_part = "" if self.api.port == default_port else f":{self.api.port}"
        url = f"{websocket_scheme}://{self.api.host}{port_part}/ws/rfc6455"
        self._ws = await self.session.ws_connect(
            url,
            protocols=("remotecontrol",),
            heartbeat=None,
            autoping=False,
            ssl=self.api.verify_ssl if self.api.use_ssl else None,
            timeout=15,
        )
        await self._ws.send_str(
            "jdev/sys/keyexchange/" + base64.b64encode(session_key).decode()
        )
        self._ensure_success(await self._read_json_response())

        key_response = await self._encrypted_request(
            f"jdev/sys/getkey2/{quote(self.api.username, safe='')}"
        )
        key_data = key_response["LL"]["value"]
        hash_algorithm = str(key_data.get("hashAlg", "SHA1")).upper()
        digest = hashlib.sha256 if hash_algorithm == "SHA256" else hashlib.sha1
        password_hash = (
            digest(f"{self.api.password}:{key_data['salt']}".encode())
            .hexdigest()
            .upper()
        )
        credentials_hash = hmac.new(
            bytes.fromhex(key_data["key"]),
            f"{self.api.username}:{password_hash}".encode(),
            digest,
        ).hexdigest()
        auth_command = (
            "jdev/sys/getjwt/"
            f"{credentials_hash}/{quote(self.api.username, safe='')}/4/"
            "8e40d9e8-9915-4d75-a2f5-0e962f16f9b1/loxone_hardware_bridge"
        )
        self._ensure_success(await self._encrypted_request(auth_command))
        self._ensure_success(
            await self._encrypted_request("jdev/sps/enablebinstatusupdate")
        )
        await self._set_connected(True)

        connected_at = time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() - connected_at >= RECONNECT_AFTER_SECONDS:
                _LOGGER.debug("Refreshing Loxone push session")
                return
            try:
                message = await asyncio.wait_for(self._read_message(), timeout=30)
            except TimeoutError:
                await self._ws.send_str("keepalive")
                continue
            if message.message_type == MESSAGE_OUT_OF_SERVICE:
                raise LoxonePushError("Miniserver is temporarily out of service")
            if message.message_type == MESSAGE_KEEPALIVE:
                continue
            if message.message_type == MESSAGE_VALUE_STATES and message.payload:
                values = parse_value_states(message.payload)
                if values:
                    await self.value_callback(values)

    async def _get_public_key(self):
        payload = await self.api._request_json("jdev/sys/getPublicKey")
        pem = str(self.api._ll_value(payload)).encode()
        try:
            return x509.load_pem_x509_certificate(pem).public_key()
        except ValueError:
            converted = pem.replace(
                b"-----BEGIN CERTIFICATE-----", b"-----BEGIN PUBLIC KEY-----"
            ).replace(b"-----END CERTIFICATE-----", b"-----END PUBLIC KEY-----")
            return serialization.load_pem_public_key(converted)

    def _encrypt_command(self, command: str) -> str:
        now = time.monotonic()
        old_salt = self._salt
        needs_new = (
            not self._salt or self._salt_uses >= 20 or now - self._salt_created >= 30
        )
        if needs_new:
            self._salt = secrets.token_hex(16)
            self._salt_created = now
            self._salt_uses = 0
        self._salt_uses += 1
        if old_salt and needs_new:
            plaintext = f"nextSalt/{old_salt}/{self._salt}/{command}\0".encode()
        else:
            plaintext = f"salt/{self._salt}/{command}\0".encode()
        plaintext += b"\0" * (-len(plaintext) % 16)
        encryptor = Cipher(
            algorithms.AES(self._aes_key), modes.CBC(self._iv)
        ).encryptor()
        encrypted = encryptor.update(plaintext) + encryptor.finalize()
        return "jdev/sys/enc/" + quote(base64.b64encode(encrypted).decode(), safe="")

    async def _encrypted_request(self, command: str) -> dict[str, Any]:
        if not self._ws:
            raise LoxonePushError("WebSocket is not connected")
        await self._ws.send_str(self._encrypt_command(command))
        response = await self._read_json_response()
        self._ensure_success(response)
        return response

    async def _read_json_response(self) -> dict[str, Any]:
        for _ in range(10):
            message = await self._read_message()
            if message.message_type != MESSAGE_TEXT or not message.payload:
                continue
            try:
                return json.loads(message.payload)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                raise LoxonePushError("Invalid JSON response from Miniserver") from err
        raise LoxonePushError("No command response received")

    async def _read_message(self) -> _Message:
        if not self._ws:
            raise LoxonePushError("WebSocket is not connected")
        first = await self._ws.receive()
        if first.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
            raise LoxonePushError("WebSocket closed")
        if first.type == WSMsgType.ERROR:
            raise LoxonePushError(str(self._ws.exception()))
        raw = first.data.encode() if isinstance(first.data, str) else first.data
        if not isinstance(raw, bytes):
            raise LoxonePushError("Unexpected WebSocket frame")
        if len(raw) != 8 or raw[0] != 3:
            return _Message(MESSAGE_TEXT, raw)
        message_type = raw[1]
        payload_length = struct.unpack("<I", raw[4:8])[0]
        if message_type in (MESSAGE_KEEPALIVE, MESSAGE_OUT_OF_SERVICE):
            return _Message(message_type, None)
        second = await self._ws.receive()
        if second.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
            raise LoxonePushError("Missing Loxone message payload")
        payload = second.data.encode() if isinstance(second.data, str) else second.data
        if not isinstance(payload, bytes):
            raise LoxonePushError("Invalid Loxone message payload")
        if payload_length and len(payload) != payload_length:
            _LOGGER.debug(
                "Loxone payload length differs: expected %s, received %s",
                payload_length,
                len(payload),
            )
        return _Message(message_type, payload)

    @staticmethod
    def _ensure_success(payload: dict[str, Any]) -> None:
        ll = payload.get("LL") or {}
        code = str(ll.get("Code", ll.get("code", "")))
        if code != "200":
            raise LoxonePushError(f"Loxone WebSocket returned code {code}")
