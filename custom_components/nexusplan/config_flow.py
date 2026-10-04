"""Pair Home Assistant with a NexusPlan project using a one-time code."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import (
    NexusPlanClient,
    NexusPlanConnectionError,
    NexusPlanError,
    NexusPlanInvalidCodeError,
    NexusPlanRateLimitedError,
)
from .const import (
    CONF_BASE_URL,
    CONF_PANEL_ADMIN_ONLY,
    CONF_PROJECT_ID,
    CONF_PROJECT_NAME,
    CONF_SHOW_PANEL,
    CONF_TOKEN,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from .sync import async_instance_info

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"
CONF_ADVANCED = "advanced"


class NexusPlanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Enter the code NexusPlan shows under Planners → Home Assistant → Connect."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NexusPlanOptionsFlow()

    async def _pair(self, code: str, base_url: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
        version = str((await async_get_integration(self.hass, DOMAIN)).version or "0")
        client = NexusPlanClient(async_get_clientsession(self.hass), base_url)
        try:
            return await client.pair(code.strip(), await async_instance_info(self.hass, version)), {}
        except NexusPlanInvalidCodeError:
            return None, {CONF_CODE: "invalid_code"}
        except NexusPlanRateLimitedError:
            return None, {"base": "rate_limited"}
        except NexusPlanConnectionError:
            return None, {"base": "cannot_connect"}
        except NexusPlanError:
            _LOGGER.exception("Unexpected error pairing with NexusPlan")
            return None, {"base": "unknown"}

    def _schema(self, with_address: bool) -> vol.Schema:
        fields: dict[Any, Any] = {vol.Required(CONF_CODE): str}
        if with_address:
            # Collapsed: only a developer pointing at a test server changes it.
            fields[vol.Optional(CONF_ADVANCED)] = section(
                vol.Schema({vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str}), {"collapsed": True})
        return vol.Schema(fields)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = (user_input.get(CONF_ADVANCED) or {}).get(CONF_BASE_URL, DEFAULT_BASE_URL).rstrip("/")
            result, errors = await self._pair(user_input[CONF_CODE], base_url)
            if result:
                project = result["project"]
                await self.async_set_unique_id(project["id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=project["name"],
                    data={CONF_BASE_URL: base_url, CONF_TOKEN: result["token"],
                          CONF_PROJECT_ID: project["id"], CONF_PROJECT_NAME: project["name"]},
                )
        return self.async_show_form(step_id="user", data_schema=self._schema(True), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._pair(user_input[CONF_CODE], entry.data[CONF_BASE_URL])
            if result:
                if result["project"]["id"] != entry.data[CONF_PROJECT_ID]:
                    return self.async_abort(reason="wrong_project")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_TOKEN: result["token"]})
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=self._schema(False), errors=errors,
            description_placeholders={"project": entry.data[CONF_PROJECT_NAME]},
        )


class NexusPlanOptionsFlow(OptionsFlow):
    """Whether the plan appears in the sidebar, and for whom."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_SHOW_PANEL, default=opts.get(CONF_SHOW_PANEL, True)): bool,
            vol.Required(CONF_PANEL_ADMIN_ONLY, default=opts.get(CONF_PANEL_ADMIN_ONLY, False)): bool,
        }))
