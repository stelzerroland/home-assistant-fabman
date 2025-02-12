"""Init der Fabman-Integration."""
import asyncio
from datetime import timedelta
import logging

import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import aiohttp_client

from .const import DOMAIN  # Wir definieren DOMAIN häufig auch in einer separaten Datei, z. B. const.py

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor"]


class FabmanDataUpdateCoordinator(DataUpdateCoordinator):
    """Koordiniert die Aktualisierung der Fabman-Ressourcen."""

    def __init__(self, hass: HomeAssistant, api):
        super().__init__(
            hass,
            _LOGGER,
            name="Fabman coordinator",
            update_interval=timedelta(seconds=10),
        )
        self.api = api

    async def _async_update_data(self):
        """Hole die Daten von der Fabman API."""
        try:
            async with async_timeout.timeout(10):
                resources = await self.api.get_resources()
                return resources
        except Exception as err:
            raise UpdateFailed(f"Error fetching Fabman resources: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setze die Integration aus dem Config Flow auf."""
    from .api import FabmanAPI
    from homeassistant.helpers import aiohttp_client

    session = aiohttp_client.async_get_clientsession(hass)
    base_url = entry.data.get("url", "https://fabman.io/api/v1")
    api_key = entry.data.get("api_key")

    api = FabmanAPI(session, base_url, api_key)
    coordinator = FabmanDataUpdateCoordinator(hass, api)
    # Erster Datenabruf
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Verwende nun async_forward_entry_setups statt async_setup_platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entlade die Integration."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
