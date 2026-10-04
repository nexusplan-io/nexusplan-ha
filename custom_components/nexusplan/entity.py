"""Shared base for the integration's status entities."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from . import NexusPlanConfigEntry
from .const import CONF_BASE_URL, CONF_PROJECT_ID, CONF_PROJECT_NAME, DOMAIN, SIGNAL_SYNC_UPDATED


class NexusPlanEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: NexusPlanConfigEntry, key: str) -> None:
        self.entry = entry
        self.sync = entry.runtime_data.sync
        project_id = entry.data[CONF_PROJECT_ID]
        self._attr_unique_id = f"{project_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, project_id)},
            name=f"NexusPlan · {entry.data[CONF_PROJECT_NAME]}",
            manufacturer="NexusPlan",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"{entry.data[CONF_BASE_URL]}/projects/{project_id}",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, f"{SIGNAL_SYNC_UPDATED}_{self.entry.entry_id}", self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
