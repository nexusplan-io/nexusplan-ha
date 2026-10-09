"""Keeps NexusPlan's copy of this home current. Push-only, read-only."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    instance_id,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import NexusPlanAuthError, NexusPlanClient, NexusPlanError, NexusPlanRateLimitedError
from .const import REGISTRY_DEBOUNCE_SECONDS, SIGNAL_INTERVAL, SIGNAL_SYNC_UPDATED
from .registry import build_registry, extract_signals

_LOGGER = logging.getLogger(__name__)


async def async_instance_info(hass: HomeAssistant, integration_version: str) -> dict[str, Any]:
    """What NexusPlan is told about this Home Assistant — no address, no location."""
    return {
        "instanceId": await instance_id.async_get(hass),
        "instanceName": hass.config.location_name,
        "haVersion": HA_VERSION,
        "integrationVersion": integration_version,
    }


class NexusPlanSync:
    """Pushes the registry on change and radio readings on a timer."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: NexusPlanClient, integration_version: str) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.integration_version = integration_version
        self.last_registry_sync: datetime | None = None
        self.last_signal_sync: datetime | None = None
        self.last_error: str | None = None
        # Set on the first 401. Nothing is pushed again until the person
        # re-pairs, which reloads the entry with a fresh token.
        self.needs_reauth = False
        self.counts: dict[str, int] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._registry_timer: CALLBACK_TYPE | None = None
        # A registry push that did not get through (NexusPlan busy, rate-limited
        # or unreachable). Without this the change was dropped until the next
        # edit in Home Assistant, and NexusPlan quietly kept a stale registry.
        # It is retried when NexusPlan's Retry-After says, or on the next signal
        # tick (every 5 minutes) — whichever comes first.
        self.registry_pending = False
        self._retry_timer: CALLBACK_TYPE | None = None
        self._retry_after: int | None = None

    @property
    def connected(self) -> bool:
        return self.last_error is None and self.last_registry_sync is not None

    async def async_start(self) -> None:
        for event in (
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            ar.EVENT_AREA_REGISTRY_UPDATED,
            fr.EVENT_FLOOR_REGISTRY_UPDATED,
        ):
            self._unsubs.append(self.hass.bus.async_listen(event, self._on_registry_event))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_signal_timer, SIGNAL_INTERVAL))
        await self.async_sync_all()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._registry_timer:
            self._registry_timer()
            self._registry_timer = None
        if self._retry_timer:
            self._retry_timer()
            self._retry_timer = None

    @callback
    def _on_registry_event(self, _event: Event) -> None:
        if self._registry_timer:
            self._registry_timer()
        self._registry_timer = async_call_later(self.hass, REGISTRY_DEBOUNCE_SECONDS, self._on_registry_timer)

    async def _on_registry_timer(self, _now: datetime) -> None:
        self._registry_timer = None
        await self.async_push_registry()

    async def _on_retry_timer(self, _now: datetime) -> None:
        self._retry_timer = None
        if self.registry_pending:
            await self.async_push_registry()

    async def _on_signal_timer(self, _now: datetime) -> None:
        if self.registry_pending and not self._retry_timer:
            await self.async_push_registry()
        await self.async_push_signals()

    async def async_sync_all(self) -> None:
        await self.async_push_registry()
        await self.async_push_signals()

    async def async_push_registry(self) -> None:
        payload = build_registry(self.hass)
        payload["instance"] = await async_instance_info(self.hass, self.integration_version)
        self._retry_after = None
        if await self._run(self.client.put_registry(payload)):
            self.registry_pending = False
            self.last_registry_sync = dt_util.utcnow()
            self.counts = {k: len(payload[k]) for k in ("floors", "areas", "devices", "entities")}
            self._updated()
            return
        if self.needs_reauth:
            return                       # re-pairing reloads the entry and pushes everything
        self.registry_pending = True
        if self._retry_after is not None and not self._retry_timer:
            # Rebuilt at retry time, so the retry carries whatever changed since.
            self._retry_timer = async_call_later(self.hass, min(self._retry_after + 5, 3600), self._on_retry_timer)

    async def async_push_signals(self) -> None:
        readings = extract_signals(self.hass)
        if await self._run(self.client.post_signals(readings)):
            self.last_signal_sync = dt_util.utcnow()
            self.counts["signals"] = len(readings)
            self._updated()

    async def _run(self, coro: Any) -> bool:
        if self.needs_reauth:
            coro.close()
            return False
        try:
            await coro
        except NexusPlanAuthError:
            # Disconnected in NexusPlan (or the token is otherwise dead): stop
            # and ask the person to pair again, rather than retry forever.
            _LOGGER.warning("NexusPlan rejected the link; asking to re-pair")
            self.needs_reauth = True
            self.last_error = "Disconnected in NexusPlan — re-pair this integration"
            self._updated()
            self.entry.async_start_reauth(self.hass)
            return False
        except NexusPlanError as err:
            if isinstance(err, NexusPlanRateLimitedError):
                self._retry_after = err.retry_after
            if self.last_error != str(err):
                _LOGGER.warning("NexusPlan sync failed: %s", err)
            self.last_error = str(err)
            self._updated()
            return False
        if self.last_error:
            _LOGGER.info("NexusPlan sync recovered")
        self.last_error = None
        return True

    @callback
    def _updated(self) -> None:
        async_dispatcher_send(self.hass, f"{SIGNAL_SYNC_UPDATED}_{self.entry.entry_id}")
