"""Diagnostics for Loxone Hardware Bridge."""

from __future__ import annotations

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import LoxoneHardwareConfigEntry

TO_REDACT = {"password", "username", "IP", "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LoxoneHardwareConfigEntry
) -> dict:
    """Return redacted diagnostics."""
    return async_redact_data(
        {
            "config": dict(entry.data),
            "options": dict(entry.options),
            "data": asdict(entry.runtime_data.coordinator.data),
            "push_mappings": len(entry.runtime_data.coordinator.push_mapping),
        },
        TO_REDACT,
    )
