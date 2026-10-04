"""Diagnostics — the link token is never included."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NexusPlanConfigEntry
from .const import CONF_TOKEN
from .registry import build_registry, extract_signals


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: NexusPlanConfigEntry) -> dict[str, Any]:
    sync = entry.runtime_data.sync
    registry = build_registry(hass)
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_TOKEN}),
        "sync": {
            "connected": sync.connected,
            "last_registry_sync": sync.last_registry_sync,
            "last_signal_sync": sync.last_signal_sync,
            "last_error": sync.last_error,
            "counts": sync.counts,
        },
        "would_send": {k: len(v) for k, v in registry.items()},
        "signal_entities": [r["entity_id"] for r in extract_signals(hass)],
    }
