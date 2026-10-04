"""Whether the link to NexusPlan is working."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NexusPlanConfigEntry
from .entity import NexusPlanEntity


async def async_setup_entry(hass: HomeAssistant, entry: NexusPlanConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([NexusPlanConnected(entry, "connected")])


class NexusPlanConnected(NexusPlanEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.sync.connected

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {"last_error": self.sync.last_error}
