"""The pairing flow."""

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nexusplan.const import CONF_BASE_URL, CONF_PROJECT_ID, CONF_PROJECT_NAME, CONF_TOKEN, DEFAULT_BASE_URL, DOMAIN

PAIR = f"{DEFAULT_BASE_URL}/api/ha-link/pair"
GOOD = {"token": "nxh_abc", "project": {"id": "p1", "name": "Maple Street"}}


async def test_pairs_with_a_code(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(PAIR, json=GOOD, status=201)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "abcd-1234"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Maple Street"
    assert result["data"] == {CONF_BASE_URL: DEFAULT_BASE_URL, CONF_TOKEN: "nxh_abc", CONF_PROJECT_ID: "p1", CONF_PROJECT_NAME: "Maple Street"}
    sent = aioclient_mock.mock_calls[0][2]
    assert sent["code"] == "abcd-1234"
    # What NexusPlan is told about this home: no address, no location.
    assert set(sent["instance"]) == {"instanceId", "instanceName", "haVersion", "integrationVersion"}


async def test_a_development_server_can_be_chosen(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post("https://dev.example/api/ha-link/pair", json=GOOD, status=201)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "ABCD1234", "advanced": {"base_url": "https://dev.example/"}})
    assert result["data"][CONF_BASE_URL] == "https://dev.example"


async def test_wrong_code(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(PAIR, json={"error": "bad", "code": "invalid_code"}, status=400)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "ZZZZ-ZZZZ"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"code": "invalid_code"}


async def test_nexusplan_unreachable(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(PAIR, status=502)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "ABCD-1234"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_same_project_twice_is_refused(hass: HomeAssistant, aioclient_mock) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="p1", data={}).add_to_hass(hass)
    aioclient_mock.post(PAIR, json=GOOD, status=201)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "ABCD-1234"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="p1", title="Maple Street",
                            data={CONF_BASE_URL: DEFAULT_BASE_URL, CONF_TOKEN: "nxh_old", CONF_PROJECT_ID: "p1", CONF_PROJECT_NAME: "Maple Street"})
    entry.add_to_hass(hass)
    return entry


async def test_reauth_replaces_the_token(hass: HomeAssistant, aioclient_mock) -> None:
    entry = _entry(hass)
    aioclient_mock.post(PAIR, json={**GOOD, "token": "nxh_new"}, status=201)
    aioclient_mock.get(f"{DEFAULT_BASE_URL}/api/ha-link/me", json={"project": {"id": "p1", "name": "Maple Street"}})
    aioclient_mock.put(f"{DEFAULT_BASE_URL}/api/ha-link/registry", json={"ok": True})
    aioclient_mock.post(f"{DEFAULT_BASE_URL}/api/ha-link/signals", json={"ok": True})
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "ABCD-1234"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "nxh_new"
    # The flow reloads the entry in the background; let that finish (the entry
    # syncs with the new token), then unload it so its 5-minute signal timer is
    # cancelled — otherwise teardown races the reload and sees a lingering timer.
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_reauth_with_another_projects_code(hass: HomeAssistant, aioclient_mock) -> None:
    entry = _entry(hass)
    aioclient_mock.post(PAIR, json={"token": "nxh_x", "project": {"id": "p2", "name": "Other"}}, status=201)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "ABCD-1234"})
    assert result["reason"] == "wrong_project"
    assert entry.data[CONF_TOKEN] == "nxh_old"


async def test_too_many_attempts_says_so(hass: HomeAssistant, aioclient_mock) -> None:
    """A 429 is not "cannot connect" — the person must be told to wait."""
    aioclient_mock.post(PAIR, json={"error": "Too many attempts.", "code": "rate_limited"}, status=429)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "ABCD-1234"})
    assert result["errors"] == {"base": "rate_limited"}
