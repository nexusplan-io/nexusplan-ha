"""What the integration reads from Home Assistant — and, as importantly, what it does not.

READ-ONLY. Nothing here calls a service, changes a state or edits a registry.

Sent to NexusPlan:
  * floors, areas, devices (name, manufacturer, model, area, which integration);
  * the entities that represent physical things, so a placed device can be
    linked to one (entity id, device, domain, device class, name — NO state);
  * numeric radio readings: Zigbee LQI and Wi-Fi/BLE RSSI, from the sensors the
    radio integrations already create.

Never sent: any other entity state, attributes, history, people, zones,
locations, automations, or anything from the auth system.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, PERCENTAGE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)

# Entity domains that stand for a physical thing a person would place on a plan.
PLACEABLE_DOMAINS = frozenset({
    "alarm_control_panel", "binary_sensor", "button", "camera", "climate", "cover", "event",
    "fan", "humidifier", "lawn_mower", "light", "lock", "media_player", "remote", "sensor",
    "siren", "switch", "vacuum", "valve", "water_heater",
})


def build_registry(hass: HomeAssistant) -> dict[str, Any]:
    """Floors, areas, devices and placeable entities — no states."""
    floor_reg = fr.async_get(hass)
    area_reg = ar.async_get(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    floors = [
        {"floor_id": f.floor_id, "name": f.name, "level": f.level}
        for f in floor_reg.async_list_floors()
    ]
    areas = [
        {"area_id": a.id, "name": a.name, "floor_id": a.floor_id}
        for a in area_reg.async_list_areas()
    ]

    devices = []
    for d in device_reg.devices:
        if d.disabled_by is not None:
            continue
        integrations = sorted({
            entry.domain
            for entry_id in d.config_entries
            if (entry := hass.config_entries.async_get_entry(entry_id)) is not None
        })
        devices.append({
            "id": d.id,
            "name": d.name,
            "name_by_user": d.name_by_user,
            "manufacturer": d.manufacturer,
            "model": d.model,
            "model_id": d.model_id,
            "area_id": d.area_id,
            "via_device_id": d.via_device_id,
            "integrations": integrations,
            "entry_type": d.entry_type.value if d.entry_type else None,
        })

    entities = []
    for e in entity_reg.entities.values():
        if e.disabled_by is not None or e.domain not in PLACEABLE_DOMAINS:
            continue
        # Loose sensors with no device are noise for a floor plan — except the
        # radio readings, which a person may want to see even so.
        if e.device_id is None and classify_signal_entity(e.entity_id, e.unit_of_measurement, e.device_class or e.original_device_class) is None:
            continue
        entities.append({
            "entity_id": e.entity_id,
            "device_id": e.device_id,
            "platform": e.platform,
            "device_class": e.device_class or e.original_device_class,
            "unit": e.unit_of_measurement,
            "area_id": e.area_id,
            "name": e.name or e.original_name,
            "entity_category": e.entity_category.value if e.entity_category else None,
        })

    return {"floors": floors, "areas": areas, "devices": devices, "entities": entities}


def classify_signal_entity(entity_id: str, unit: str | None, device_class: str | None) -> str | None:
    """Which kind of radio reading an entity is, if any.

    Zigbee2MQTT publishes `<name>_linkquality` in "lqi"; ZHA a diagnostic
    `<name>_lqi` with no unit (disabled by default — the person must enable it);
    Wi-Fi and BLE integrations use device_class signal_strength in dBm or %.
    """
    if not entity_id.startswith("sensor."):
        return None
    unit_l = (unit or "").lower()
    if unit_l == "lqi" or entity_id.endswith(("_linkquality", "_lqi")):
        return "lqi"
    if device_class == "signal_strength" or entity_id.endswith(("_rssi", "_signal_strength")):
        if unit == SIGNAL_STRENGTH_DECIBELS_MILLIWATT:
            return "rssi_dbm"
        if unit == PERCENTAGE:
            return "rssi_pct"
    return None


def _reading(state: State, kind: str, device_id: str | None) -> dict[str, Any] | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None                 # "unknown", "unavailable"
    return {
        "entity_id": state.entity_id,
        "device_id": device_id,
        "kind": kind,
        "value": value,
        "observed_at": state.last_updated.isoformat(),
    }


def extract_signals(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Current numeric radio readings, one per sensor."""
    entity_reg = er.async_get(hass)
    readings = []
    for state in hass.states.async_all("sensor"):
        entry = entity_reg.async_get(state.entity_id)
        kind = classify_signal_entity(
            state.entity_id,
            state.attributes.get("unit_of_measurement"),
            state.attributes.get("device_class"),
        )
        if kind is None:
            continue
        if (r := _reading(state, kind, entry.device_id if entry else None)) is not None:
            readings.append(r)
    return readings
