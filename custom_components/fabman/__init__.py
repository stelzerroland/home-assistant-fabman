"""Set up and unload the Fabman integration."""

import asyncio
import logging

from aiohttp.web import Response
from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import FabmanDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Keep existing installations' configured endpoint working during upgrades.
WEBHOOK_ID = "fabman_webhook"
PLATFORMS = ["switch", "sensor", "binary_sensor"]


def entry_webhook_id(entry_id):
    """Return a stable webhook ID belonging to one entry."""
    return f"{WEBHOOK_ID}_{entry_id}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the coordinator, entities and entry-specific webhook."""
    coordinator = FabmanDataUpdateCoordinator(hass, entry.data)
    coordinators = hass.data.setdefault(DOMAIN, {})
    webhook_id = entry_webhook_id(entry.entry_id)
    registered = []
    try:
        await coordinator.async_config_entry_first_refresh()
        if isinstance(coordinator.data, dict) and any(
            isinstance(other.data, dict) and coordinator.data.keys() & other.data.keys()
            for other in coordinators.values()
        ):
            _LOGGER.warning(
                "Overlapping Fabman resource IDs across entries: legacy sensor/switch "
                "IDs can collide. Activity sensor IDs are scoped to each entry"
            )
        coordinators[entry.entry_id] = coordinator
        async_register(hass, DOMAIN, "Fabman Webhook", webhook_id, handle_webhook)
        registered.append(webhook_id)
        if len(coordinators) == 1:
            async_register(
                hass, DOMAIN, "Fabman Legacy Webhook", WEBHOOK_ID, handle_webhook
            )
            registered.append(WEBHOOK_ID)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        coordinators.pop(entry.entry_id, None)
        for registered_id in registered:
            if registered_id != WEBHOOK_ID or not coordinators:
                async_unregister(hass, registered_id)
        coordinator.async_cancel_pending_updates()
        raise
    _LOGGER.debug("Fabman webhook registered for entry %s", entry.entry_id)
    return True


async def handle_webhook(hass: HomeAssistant, webhook_id: str, request):
    """Refresh authoritative API data for the entries addressed by this URL."""
    try:
        data = await request.json()
    except (ValueError, TypeError):
        return Response(text="Invalid JSON", status=400)
    if not isinstance(data, dict):
        return Response(text="Expected a JSON object", status=400)

    coordinators = hass.data.get(DOMAIN, {})
    if webhook_id == WEBHOOK_ID:
        # The old URL cannot identify an account. Refresh all configured accounts;
        # never apply one account's payload to another account's resource state.
        targets = list(coordinators.values())
    else:
        targets = [
            coordinator
            for entry_id, coordinator in coordinators.items()
            if entry_webhook_id(entry_id) == webhook_id
        ]
    if not targets:
        return Response(text="Fabman entry unavailable", status=503)

    results = await asyncio.gather(
        *(coordinator.async_request_refresh() for coordinator in targets),
        return_exceptions=True,
    )
    if any(isinstance(result, Exception) for result in results) or any(
        not coordinator.last_update_success for coordinator in targets
    ):
        return Response(text="Fabman refresh failed", status=503)
    return Response(text="Fabman resources updated", status=200)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove only this entry's callbacks after its platforms unload."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinators = hass.data.get(DOMAIN, {})
    coordinator = coordinators.pop(entry.entry_id, None)
    if coordinator is not None:
        coordinator.async_cancel_pending_updates()
    async_unregister(hass, entry_webhook_id(entry.entry_id))
    if not coordinators:
        async_unregister(hass, WEBHOOK_ID)
    return True
