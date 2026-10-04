"""What is read from Home Assistant — and what is not."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, floor_registry as fr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nexusplan.registry import build_registry, classify_signal_entity, extract_signals


@pytest.mark.parametrize(("entity_id", "unit", "device_class", "kind"), [
    ("sensor.hall_motion_linkquality", "lqi", None, "lqi"),            # Zigbee2MQTT
    ("sensor.kitchen_plug_lqi", None, None, "lqi"),                     # ZHA diagnostic
    ("sensor.camera_rssi", "dBm", "signal_strength", "rssi_dbm"),       # Wi-Fi / ESPHome
    ("sensor.tag_signal_strength", "%", "signal_strength", "rssi_pct"),
    ("sensor.living_temperature", "°C", "temperature", None),
    ("binary_sensor.hall_motion_lqi", None, None, None),               # not a sensor
])
def test_classify(entity_id, unit, device_class, kind) -> None:
    assert classify_signal_entity(entity_id, unit, device_class) == kind


async def test_registry_has_structure_but_no_states(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain="mqtt")
    entry.add_to_hass(hass)
    floor = fr.async_get(hass).async_create("Ground", level=0)
    area = ar.async_get(hass).async_create("Hall", floor_id=floor.floor_id)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("mqtt", "0x00158d")},
                                                  name="Hall motion", manufacturer="Aqara", model="RTCGQ11LM")
    dr.async_get(hass).async_update_device(dev.id, area_id=area.id)
    er.async_get(hass).async_get_or_create("binary_sensor", "mqtt", "motion1", device_id=dev.id, original_device_class="motion")
    hass.states.async_set("binary_sensor.hall_motion", "on", {"secret_attr": "do not send"})

    reg = build_registry(hass)
    assert [f["name"] for f in reg["floors"]] == ["Ground"]
    assert reg["areas"] == [{"area_id": area.id, "name": "Hall", "floor_id": floor.floor_id}]
    d = next(x for x in reg["devices"] if x["id"] == dev.id)
    assert (d["manufacturer"], d["model"], d["area_id"], d["integrations"]) == ("Aqara", "RTCGQ11LM", area.id, ["mqtt"])
    assert any(e["device_id"] == dev.id and e["device_class"] == "motion" for e in reg["entities"])
    blob = str(reg)
    assert "do not send" not in blob and "'state'" not in blob


async def test_signals_are_numeric_readings_only(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.hall_linkquality", "187", {"unit_of_measurement": "lqi"})
    hass.states.async_set("sensor.cam_rssi", "-61", {"unit_of_measurement": "dBm", "device_class": "signal_strength"})
    hass.states.async_set("sensor.gone_lqi", "unavailable", {})
    hass.states.async_set("sensor.living_temperature", "21.5", {"unit_of_measurement": "°C"})
    readings = {r["entity_id"]: r for r in extract_signals(hass)}
    assert set(readings) == {"sensor.hall_linkquality", "sensor.cam_rssi"}
    assert readings["sensor.hall_linkquality"]["value"] == 187.0 and readings["sensor.cam_rssi"]["kind"] == "rssi_dbm"
