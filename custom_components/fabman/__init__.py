"""Init of the Fabman Integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.helpers.typing import ConfigType
from aiohttp.web import Response  # Für HTTP-Antworten in handle_webhook
from .const import DOMAIN
from .coordinator import FabmanDataUpdateCoordinator  # Import der Klasse aus coordinator.py

_LOGGER = logging.getLogger(__name__)

WEBHOOK_ID = "fabman_webhook"  # Webhook-Name für Fabman
WEBHOOK_URL = f"/api/webhook/{WEBHOOK_ID}"  # Webhook-Endpoint in HA

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

    # ✅ Webhook-Handler-Funktion definieren (vor async_register)
    async def handle_webhook(hass: HomeAssistant, webhook_id: str, request):
        """Handle incoming Webhook from Fabman."""
        try:
            data = await request.json()
            _LOGGER.info(f"📡 Received Fabman Webhook: {data}")

            # Stelle sicher, dass der Koordinator geladen ist
            coordinator = hass.data[DOMAIN].get(next(iter(hass.data[DOMAIN])), None)
            if not coordinator:
                _LOGGER.error("❌ Fabman Coordinator not found!")
                return Response(text="❌ Fabman Coordinator not found!", status=500)

            # Starte eine vollständige Aktualisierung aller Ressourcen
            _LOGGER.info("🔄 Webhook ausgelöst – Starte vollständige Aktualisierung aller Fabman-Geräte...")
            await coordinator.async_refresh()




            # Falls das Gerät eine Tür ist, plane ein erneutes Update nach maxOfflineUsage Sekunden
            resource = data.get("details", {}).get("resource", {})
            control_type = resource.get("controlType", "")
            max_offline_usage = resource.get("maxOfflineUsage", 0)

            if control_type == "door" and max_offline_usage > 0:
                last_used_at = resource.get("lastUsed", {}).get("at")
                if last_used_at:
                    last_used_at = dt_util.parse_datetime(last_used_at)
                    close_time = last_used_at + timedelta(seconds=max_offline_usage)
                    delay = (close_time - dt_util.utcnow()).total_seconds()

                    if delay > 0:
                        _LOGGER.info(f"🕒 Tür wird in {delay:.1f} Sekunden erneut überprüft...")
                        hass.loop.call_later(delay, lambda: hass.async_create_task(coordinator.async_refresh()))





            return Response(text="✅ Fabman Geräte-Update erfolgreich gestartet.", status=200)

        except Exception as e:
            _LOGGER.error(f"❌ Fehler beim Verarbeiten des Fabman Webhooks: {e}")
            return Response(text=f"❌ Fehler beim Verarbeiten des Fabman Webhooks: {e}", status=500)

    # ✅ Webhook sicher registrieren (Vorher prüfen, ob er existiert)
    try:
        async_unregister(hass, WEBHOOK_ID)
        _LOGGER.info(f"🔄 Webhook {WEBHOOK_ID} entfernt (falls er existierte).")
    except ValueError:
        _LOGGER.info(f"✅ Kein vorhandener Webhook für {WEBHOOK_ID}, Registrierung läuft.")

    # Jetzt sicher registrieren
    async_register(hass, DOMAIN, "Fabman Webhook", WEBHOOK_ID, handle_webhook)
    _LOGGER.info(f"✅ Fabman Webhook registered at {WEBHOOK_URL}")

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Fabman integration and remove webhook."""
    async_unregister(hass, WEBHOOK_ID)
    _LOGGER.info("🚫 Fabman Webhook unregistered")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
