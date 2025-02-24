"""Init der Fabman-Integration."""
import asyncio
from datetime import timedelta
import logging
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import FabmanDataUpdateCoordinator  # Importiere die Klasse aus coordinator.py

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .api import FabmanAPI
    from homeassistant.helpers import aiohttp_client
    from .const import CONF_API_URL, DEFAULT_API_URL, CONF_API_TOKEN

    session = aiohttp_client.async_get_clientsession(hass)
    base_url = entry.data.get(CONF_API_URL, DEFAULT_API_URL)
    api_key = entry.data.get(CONF_API_TOKEN)

    api = FabmanAPI(session, base_url, api_key)
    coordinator = FabmanDataUpdateCoordinator(hass, entry.data)
    # Setze die fehlenden Attribute (falls nötig)
    coordinator.api_url = base_url
    coordinator.api_token = api_key

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
