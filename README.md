# NexusPlan for Home Assistant

Keep a [NexusPlan](https://nexusplan.io) floor plan in step with your Home Assistant.

NexusPlan plans a smart home — walls, rooms, devices and simulated wireless coverage.
This integration connects a NexusPlan project to your Home Assistant so the plan knows
about your **real** devices and areas, and can compare the coverage it predicted with the
**signal your radios actually measure** (Zigbee LQI, Wi-Fi and BLE RSSI).

## What it does — and does not do

**Reads** (and sends to your NexusPlan project):
- floors and areas;
- devices — name, manufacturer, model, area, and which integration they come from;
- the entities that represent physical things — entity id, device, type and name, **no state**;
- numeric radio readings from the sensors your radio integrations already create:
  Zigbee2MQTT `*_linkquality`, ZHA `*_lqi`, and Wi-Fi/BLE signal-strength sensors.

**Never**:
- controls a device, calls a service, or changes an entity, area or automation — it is read-only;
- sends any other entity state, attribute or history, or anything about people, zones or locations;
- needs remote access — it connects **out** to NexusPlan over HTTPS, so it works with a
  Home Assistant that is only on your home network. NexusPlan never connects in, and holds
  no credential to your Home Assistant.

## Requirements

- Home Assistant 2025.3 or newer.
- A NexusPlan account — any plan, Free included.

## Install

**With HACS** (recommended):

1. In HACS, open the menu (⋮) → **Custom repositories**, add
   `https://github.com/nexusplan-io/nexusplan-ha` with type **Integration**.
2. Search HACS for **NexusPlan**, install it, then restart Home Assistant.

**By hand:** download [nexusplan-ha.zip](https://nexusplan.io/downloads/nexusplan-ha.zip),
copy its `nexusplan` folder into Home Assistant's `config/custom_components/`, and restart.

Full guide, with screenshots: https://nexusplan.io/docs/home-assistant/connect/

## Connect a project

1. In NexusPlan, open the project, then **Planners → Home Assistant → Connect Home Assistant**,
   and click **Create a pairing code**.
2. In Home Assistant, go to **Settings → Devices & services → Add integration → NexusPlan**
   and enter the code. Codes last 10 minutes and work once.

That is all. The registry is sent on start and whenever it changes; signal readings every
five minutes. **NexusPlan · <project>** appears as a service with diagnostic sensors —
*Connected*, *Last device sync*, *Last signal sync*, *Devices synced*.

**NexusPlan** also appears in the sidebar: the plan, read-only for anyone who can see it;
**Sign in to edit** inside it to edit. Hide it, or limit it to administrators, under the
integration's **Configure**.

To disconnect, remove the integration here, or click **Disconnect** in NexusPlan — Home
Assistant will then ask to be paired again.

## Services

- `nexusplan.sync_now` — send everything now.
- `nexusplan.get_map` (returns a response) — the NexusPlan plan as spatial context: floors,
  walls with their signal loss, rooms and devices in metres, each with its linked entity.
  Same shape as the [ha-spatial-context](https://github.com/Greminn/ha-spatial-context)
  integration's export, so AI agents that read one read the other.

## Zigbee signal readings

- **Zigbee2MQTT** publishes `linkquality` sensors by default.
- **ZHA**'s `LQI` and `RSSI` sensors exist but are **disabled by default** — enable them on each
  device (entity settings → Enable) for NexusPlan to see them.

## Troubleshooting

- *Connected* is off with "Disconnected in NexusPlan": the link was removed in NexusPlan;
  follow the **Reconfigure** prompt with a new code.
- **Download diagnostics** from the integration page shows exactly what would be sent —
  the link token is never included.

## Credits

The idea of giving Home Assistant spatial context, and the snapshot format NexusPlan's
`get_map` follows, come from Simon Buchanan's
[ha-spatial-context](https://github.com/Greminn/ha-spatial-context) (MIT). This integration
is a separate implementation.

## Development

```
pip install -r requirements_test.txt
python -m pytest -q
```

Every push runs HACS validation, Home Assistant's hassfest and the tests (see
`.github/workflows/`). Bug reports and pull requests are welcome in
[Issues](https://github.com/nexusplan-io/nexusplan-ha/issues); for help with your
NexusPlan account, use [nexusplan.io/contact](https://nexusplan.io/contact).

## Licence

MIT — see [LICENSE](LICENSE).

