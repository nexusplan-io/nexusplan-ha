"""Constants for the NexusPlan integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "nexusplan"

DEFAULT_BASE_URL: Final = "https://app.nexusplan.io"

CONF_BASE_URL: Final = "base_url"
CONF_TOKEN: Final = "token"
CONF_PROJECT_ID: Final = "project_id"
CONF_PROJECT_NAME: Final = "project_name"

# Radio readings change slowly and are coarse; every five minutes is plenty.
SIGNAL_INTERVAL: Final = timedelta(minutes=5)
# Registry edits arrive in bursts (a new Zigbee device creates a dozen entities
# in a second), so a registry push waits for things to settle.
REGISTRY_DEBOUNCE_SECONDS: Final = 30

SERVICE_SYNC_NOW: Final = "sync_now"
SERVICE_GET_MAP: Final = "get_map"

SIGNAL_SYNC_UPDATED: Final = f"{DOMAIN}_sync_updated"

# Options
CONF_SHOW_PANEL: Final = "show_panel"
CONF_PANEL_ADMIN_ONLY: Final = "panel_admin_only"
PANEL_ICON: Final = "mdi:floor-plan"
