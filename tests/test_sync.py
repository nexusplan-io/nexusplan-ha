"""Setup, pushing, and what happens when NexusPlan says no."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nexusplan.const import CONF_BASE_URL, CONF_PROJECT_ID, CONF_PROJECT_NAME, CONF_TOKEN, DOMAIN

BASE = "https://np.test"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="p1", title="Maple Street",
                            data={CONF_BASE_URL: BASE, CONF_TOKEN: "nxh_t", CONF_PROJECT_ID: "p1", CONF_PROJECT_NAME: "Maple Street"})
    entry.add_to_hass(hass)
    return entry


def _ok(aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", json={"ok": True})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", json={"ok": True})


async def test_setup_pushes_registry_and_signals(hass: HomeAssistant, aioclient_mock) -> None:
    hass.states.async_set("sensor.hall_linkquality", "200", {"unit_of_measurement": "lqi"})
    _ok(aioclient_mock)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    calls = {(m, str(u)): body for m, u, body, *_ in aioclient_mock.mock_calls}
    assert ("PUT", f"{BASE}/api/ha-link/registry") in calls
    readings = calls[("POST", f"{BASE}/api/ha-link/signals")]["readings"]
    assert [r["entity_id"] for r in readings] == ["sensor.hall_linkquality"]
    for m, _u, _b, headers in [(c[0], c[1], c[2], c[3]) for c in aioclient_mock.mock_calls]:
        assert headers["Authorization"] == "Bearer nxh_t"
    assert hass.states.get("binary_sensor.nexusplan_maple_street_connected").state == "on"


async def test_revoked_link_starts_reauth_and_goes_quiet(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", status=401, json={"code": "reauth"})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", status=401, json={"code": "reauth"})
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1 and flows[0]["context"]["source"] == "reauth"
    # The signal push after the registry's 401 is not attempted.
    assert not any(str(u).endswith("/signals") for _m, u, *_ in aioclient_mock.mock_calls)
    assert hass.states.get("binary_sensor.nexusplan_maple_street_connected").state == "off"


async def test_disconnected_before_start_asks_to_repair(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha-link/me", status=401, json={"code": "reauth"})
    entry = _entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN))


async def test_refused_push_is_an_error_not_a_repair(hass: HomeAssistant, aioclient_mock) -> None:
    # Home Assistant is on every NexusPlan plan, so nothing pauses a link for
    # billing any more; any other refusal is shown as an error and retried.
    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", status=403, json={"code": "forbidden", "error": "Refused"})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", status=403, json={"code": "forbidden", "error": "Refused"})
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.nexusplan_maple_street_connected")
    assert state.state == "off" and state.attributes["last_error"]
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)     # not a re-pair


async def test_nexusplan_down_at_start_retries(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha-link/me", status=503)
    entry = _entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


def _me_with_panel(aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}, "panelPath": "/embed/ha/p1?c=conn&k=key"})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", json={"ok": True})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", json={"ok": True})


def _panels(hass: HomeAssistant) -> dict:
    return {k: v for k, v in hass.data.get("frontend_panels", {}).items() if k.startswith("nexusplan-")}


async def test_plan_appears_in_the_sidebar(hass: HomeAssistant, aioclient_mock) -> None:
    _me_with_panel(aioclient_mock)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    panels = _panels(hass)
    assert len(panels) == 1
    panel = next(iter(panels.values()))
    assert panel.component_name == "iframe"
    assert panel.sidebar_title == "NexusPlan" and panel.sidebar_icon == "mdi:floor-plan"
    assert panel.config == {"url": f"{BASE}/embed/ha/p1?c=conn&k=key"}
    assert panel.require_admin is False
    # Removed with the integration.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert _panels(hass) == {}


async def test_sidebar_options(hass: HomeAssistant, aioclient_mock) -> None:
    _me_with_panel(aioclient_mock)
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"show_panel": True, "panel_admin_only": True})
    await hass.async_block_till_done()
    assert next(iter(_panels(hass).values())).require_admin is True
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"show_panel": False, "panel_admin_only": False})
    await hass.async_block_till_done()
    assert _panels(hass) == {}


def _registry_puts(aioclient_mock) -> int:
    return sum(1 for method, url, *_ in aioclient_mock.mock_calls if method == "PUT" and str(url).endswith("/api/ha-link/registry"))


async def test_rate_limited_registry_push_is_retried(hass: HomeAssistant, aioclient_mock) -> None:
    """A 429 must not drop the change: re-push after NexusPlan's Retry-After."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", status=429, headers={"Retry-After": "60"},
                       json={"error": "Too many requests", "code": "rate_limited"})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", json={"ok": True})
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sync = entry.runtime_data.sync
    assert sync.registry_pending and _registry_puts(aioclient_mock) == 1

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", json={"ok": True})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", json={"ok": True})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=70))
    await hass.async_block_till_done()
    assert _registry_puts(aioclient_mock) == 1 and not sync.registry_pending
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_failed_registry_push_catches_up_on_the_next_signal_tick(hass: HomeAssistant, aioclient_mock) -> None:
    """Any other failure (here a 503) is retried with the 5-minute signal push."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", status=503, json={"error": "busy"})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", json={"ok": True})
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sync = entry.runtime_data.sync
    assert sync.registry_pending

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{BASE}/api/ha-link/registry", json={"ok": True})
    aioclient_mock.post(f"{BASE}/api/ha-link/signals", json={"ok": True})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5, seconds=5))
    await hass.async_block_till_done()
    assert _registry_puts(aioclient_mock) == 1 and not sync.registry_pending
    assert await hass.config_entries.async_unload(entry.entry_id)
