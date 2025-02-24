import asyncio
import logging
import aiohttp
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
#from .const import UPDATE_INTERVAL, CONF_API_TOKEN, CONF_API_URL, CONF_WEBSOCKET_URL, CONF_ENABLE_PERIODIC_SYNC, CONF_POLL_INTERVAL
from .const import CONF_API_TOKEN, CONF_API_URL, CONF_WEBSOCKET_URL, CONF_ENABLE_PERIODIC_SYNC, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
from .api import FabmanAPI

_LOGGER = logging.getLogger(__name__)

class FabmanDataUpdateCoordinator(DataUpdateCoordinator):
    """Koordiniert Datenabfragen und verwaltet die WebSocket-Verbindung zu Fabman."""

    def __init__(self, hass, config):
        self.hass = hass
        self.api_token = config[CONF_API_TOKEN]
        self.api_url = config.get(CONF_API_URL)
        self.websocket_url = config.get(CONF_WEBSOCKET_URL)
        self.enable_periodic_sync = config.get(CONF_ENABLE_PERIODIC_SYNC)
        self.poll_interval = config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL) 
        self._session = async_get_clientsession(self.hass)
        self._websocket_task = None
        update_interval = timedelta(seconds=self.poll_interval) if self.enable_periodic_sync else None

        _LOGGER.debug("enable_periodic_sync=%s, poll_interval=%s", self.enable_periodic_sync, self.poll_interval)
        _LOGGER.debug("update_interval=%s", update_interval)

        super().__init__(
            hass,
            _LOGGER,
            name="Fabman Data Coordinator",
            update_interval=update_interval,
        )
        self.data = {}  # Speichert die Ressourcen, key ist die resource id

    async def _async_update_data(self):
        try:
            fabman_api = FabmanAPI(self._session, self.api_url, self.api_token)
            resources = await fabman_api.get_resources()
            new_data = {}
            for resource in resources:
                resource_id = resource.get("id")
                if resource_id:
                    new_data[resource_id] = resource
            return new_data
        except Exception as e:
            raise UpdateFailed(f"Exception beim Datenabruf: {e}")

    async def start_websocket_listener(self):
        if not self.websocket_url or not self.websocket_url.strip():
            _LOGGER.info("Keine WebSocket-URL konfiguriert, WebSocket-Listener wird nicht gestartet.")
            return
        while True:
            try:
                _LOGGER.debug("Verbinde zu Fabman WebSocket unter %s", self.websocket_url)
                async with self._session.ws_connect(self.websocket_url) as ws:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()
                            await self._handle_websocket_message(data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            _LOGGER.error("WebSocket-Fehler: %s", msg)
                            break
            except Exception as e:
                _LOGGER.error("WebSocket-Verbindungsfehler: %s", e)
            _LOGGER.debug("Versuche in 10 Sekunden erneut die WebSocket-Verbindung aufzubauen")
            await asyncio.sleep(10)

    async def _handle_websocket_message(self, message):
        """Verarbeitet eingehende WebSocket-Nachrichten und aktualisiert die Daten."""
        resource_id = message.get("resource_id")
        if not resource_id:
            _LOGGER.warning("Empfangene Nachricht ohne resource_id: %s", message)
            return
        # Aktualisiere vorhandene Resource-Daten oder füge eine neue hinzu
        if resource_id in self.data:
            self.data[resource_id].update(message)
        else:
            self.data[resource_id] = message
        _LOGGER.debug("Aktualisierte Daten für resource %s über WebSocket", resource_id)
        self.async_set_updated_data(self.data)

    async def shutdown(self):
        """Beendet alle laufenden Tasks (z. B. WebSocket-Listener)."""
        if self._websocket_task:
            self._websocket_task.cancel()
