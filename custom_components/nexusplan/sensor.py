"""When NexusPlan last received this home's data, and how much of it."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NexusPlanConfigEntry
from .entity import NexusPlanEntity


async def async_setup_entry(hass: HomeAssistant, entry: NexusPlanConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([
        NexusPlanLastSync(entry, "last_registry_sync"),
        NexusPlanLastSync(entry, "last_signal_sync"),
        NexusPlanCount(entry, "devices_synced"),
        NexusPlanCount(entry, "signals_synced"),
    ])


class NexusPlanLastSync(NexusPlanEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> datetime | None:
        return getattr(self.sync, self._attr_translation_key)


class NexusPlanCount(NexusPlanEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        key = {"devices_synced": "devices", "signals_synced": "signals"}[self._attr_translation_key]
        return self.sync.counts.get(key)
