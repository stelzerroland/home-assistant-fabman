"""Init of the Fabman Integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.helpers.typing import ConfigType
from .const import DOMAIN
from .coordinator import FabmanDataUpdateCoordinator  # Import the class from coordinator.py

_LOGGER = logging.getLogger(__name__)

WEBHOOK_ID = "fabman_webhook"  # Webhook name for Fabman
WEBHOOK_URL = f"/api/webhook/{WEBHOOK_ID}"  # Webhook endpoint in HA

PLATFORMS = ["switch", "sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Fabman integration via ConfigEntry."""
    from .api import FabmanAPI
    from homeassistant.helpers import aiohttp_client
    from .const import CONF_API_URL, DEFAULT_API_URL, CONF_API_TOKEN

    session = aiohttp_client.async_get_clientsession(hass)
    base_url = entry.data.get(CONF_API_URL, DEFAULT_API_URL)
    api_key = entry.data.get(CONF_API_TOKEN)

    api = FabmanAPI(session, base_url, api_key)
    coordinator = FabmanDataUpdateCoordinator(hass, entry.data)
    coordinator.api_url = base_url
    coordinator.api_token = api_key

    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ✅ Properly register the Webhook using async_register
    async def handle_webhook(hass: HomeAssistant, webhook_id: str, request):
        """Handle incoming Webhook from Fabman."""
        try:
            data = await request.json()
            log_message = f"📡 Received Fabman Webhook: {data}"
            _LOGGER.info(log_message)
            print(log_message)  # Ausgabe für Fabman-Webhook-Log

            # Extract resource ID and status from the Webhook
            resource = data.get("details", {}).get("resource", {})
            resource_id = resource.get("id")
            last_used = resource.get("lastUsed")

            if not resource_id:
                log_message = "⚠️ Webhook received without resource_id."
                _LOGGER.warning(log_message)
                print(log_message)
                return
            
            log_message = f"Webhook processes resource_id: {resource_id}"
            _LOGGER.debug(log_message)
            print(log_message)

            # Stelle sicher, dass der Koordinator geladen ist
            coordinator = hass.data[DOMAIN].get(next(iter(hass.data[DOMAIN])))
            if not coordinator:
                log_message = "❌ Fabman Coordinator not found!"
                _LOGGER.error(log_message)
                print(log_message)
                return

            # Stelle sicher, dass die Ressource existiert
            if resource_id not in coordinator.data:
                log_message = f"⚠️ Webhook-Update: Resource {resource_id} not found in HA!"
                _LOGGER.warning(log_message)
                print(log_message)
                return

            # Aktualisiere den Status direkt
            updated_resource = coordinator.data[resource_id].copy()
            last_used = resource.get("lastUsed")
            if last_used and "id" in last_used and "stopType" not in last_used:
                updated_resource["lastUsed"] = {"id": "set_by_webhook", "stopType": None}
            else:
                updated_resource["lastUsed"] = {"id": None, "stopType": "set_by_webhook"}

            coordinator.data[resource_id] = updated_resource
            coordinator.async_set_updated_data(coordinator.data)

            log_message = f"✅ Status of Resource {resource_id} updated successfully."
            _LOGGER.debug(log_message)
            print(log_message)

        except Exception as e:
            log_message = f"❌ Error processing Fabman Webhook: {e}"
            _LOGGER.error(log_message)
            print(log_message)

    async_register(hass, DOMAIN, "Fabman Webhook", WEBHOOK_ID, handle_webhook)
    log_message = f"✅ Fabman Webhook registered at {WEBHOOK_URL}"
    _LOGGER.info(log_message)
    print(log_message)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Fabman integration and remove webhook."""
    async_unregister(hass, WEBHOOK_ID)
    _LOGGER.info("🚫 Fabman Webhook unregistered")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
