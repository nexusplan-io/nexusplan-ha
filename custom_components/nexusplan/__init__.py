"""NexusPlan — keep a NexusPlan floor plan in step with this Home Assistant.

Pushes floors, areas, devices and Zigbee/Wi-Fi signal readings to one NexusPlan
project, so the plan can place real devices and compare predicted coverage with
what the radios actually measure. Read-only towards Home Assistant; outbound
HTTPS only, so it works without remote access.
"""

from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import NexusPlanAuthError, NexusPlanClient, NexusPlanError
from .const import (
    CONF_BASE_URL,
    CONF_PANEL_ADMIN_ONLY,
    CONF_PROJECT_NAME,
    CONF_SHOW_PANEL,
    CONF_TOKEN,
    DOMAIN,
    PANEL_ICON,
    SERVICE_GET_MAP,
    SERVICE_SYNC_NOW,
)
from .sync import NexusPlanSync

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class NexusPlanData:
    client: NexusPlanClient
    sync: NexusPlanSync
    panel_url_path: str | None = None


type NexusPlanConfigEntry = ConfigEntry[NexusPlanData]


def _entries(hass: HomeAssistant, call: ServiceCall) -> list[NexusPlanConfigEntry]:
    wanted = call.data.get("config_entry_id")
    entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN) if not wanted or e.entry_id == wanted]
    if not entries:
        raise HomeAssistantError("No NexusPlan project is connected")
    return entries


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def sync_now(call: ServiceCall) -> None:
        for entry in _entries(hass, call):
            await entry.runtime_data.sync.async_sync_all()

    async def get_map(call: ServiceCall) -> ServiceResponse:
        entry = _entries(hass, call)[0]
        try:
            return await entry.runtime_data.client.get_map()
        except NexusPlanError as err:
            raise HomeAssistantError(f"Could not fetch the NexusPlan map: {err}") from err

    target = vol.Schema({vol.Optional("config_entry_id"): cv.string})
    hass.services.async_register(DOMAIN, SERVICE_SYNC_NOW, sync_now, schema=target)
    hass.services.async_register(DOMAIN, SERVICE_GET_MAP, get_map, schema=target, supports_response=SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NexusPlanConfigEntry) -> bool:
    client = NexusPlanClient(async_get_clientsession(hass), entry.data[CONF_BASE_URL], entry.data[CONF_TOKEN])
    try:
        me = await client.me()
    except NexusPlanAuthError as err:
        raise ConfigEntryAuthFailed("This link was disconnected in NexusPlan") from err
    except NexusPlanError as err:
        raise ConfigEntryNotReady(f"NexusPlan is not reachable: {err}") from err

    version = str((await async_get_integration(hass, DOMAIN)).version or "0")
    sync = NexusPlanSync(hass, entry, client, version)
    entry.runtime_data = NexusPlanData(client=client, sync=sync)
    _register_panel(hass, entry, me.get("panelPath"))
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await sync.async_start()
    return True


def _register_panel(hass: HomeAssistant, entry: NexusPlanConfigEntry, panel_path: str | None) -> None:
    """The NexusPlan plan in the sidebar: read-only until someone signs in to edit.

    Home Assistant's built-in iframe panel frames NexusPlan's /embed page. Its URL
    carries a view key tied to this link (so anyone who can open this sidebar can
    view the plan); editing needs a NexusPlan sign-in inside the frame.
    """
    if not panel_path or not entry.options.get(CONF_SHOW_PANEL, True):
        return
    url_path = f"nexusplan-{entry.entry_id[-6:].lower()}"
    several = len(hass.config_entries.async_entries(DOMAIN)) > 1
    frontend.async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title=f"NexusPlan · {entry.data[CONF_PROJECT_NAME]}" if several else "NexusPlan",
        sidebar_icon=PANEL_ICON,
        frontend_url_path=url_path,
        config={"url": f"{entry.data[CONF_BASE_URL]}{panel_path}"},
        require_admin=entry.options.get(CONF_PANEL_ADMIN_ONLY, False),
        update=True,
    )
    entry.runtime_data.panel_url_path = url_path


async def _options_updated(hass: HomeAssistant, entry: NexusPlanConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NexusPlanConfigEntry) -> bool:
    entry.runtime_data.sync.async_stop()
    if entry.runtime_data.panel_url_path:
        frontend.async_remove_panel(hass, entry.runtime_data.panel_url_path)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
