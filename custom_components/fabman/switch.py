import logging
import aiohttp
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, CONF_API_URL
from .helpers import get_device_info

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Richtet die Switch-Plattform ein – nur für Ressourcen mit Bridge."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    for resource_id, resource in coordinator.data.items():
        bridge_data = resource.get("_embedded", {}).get("bridge")
        if bridge_data:
            entities.append(FabmanSwitch(coordinator, resource_id))
        else:
            _LOGGER.debug("Ressource %s besitzt keine Bridge – Schalter wird nicht erstellt", resource_id)
    async_add_entities(entities)

class FabmanSwitch(CoordinatorEntity, SwitchEntity):
    """Repräsentiert einen Fabman-Bridge-Schalter für Ressourcen mit Bridge."""

    def __init__(self, coordinator, resource_id):
        """Initialisiert den Schalter anhand des Coordinators und der Resource-ID."""
        super().__init__(coordinator)
        self._resource_id = resource_id
        self._attr_unique_id = f"fabman_resource_{resource_id}"
        #self._attr_name = self._generate_friendly_name()
        self._attr_name = f"fabman_resource_{resource_id}"

    @property
    def resource(self):
        """Gibt die aktuellen Daten der Ressource aus dem Coordinator zurück."""
        return self.coordinator.data.get(self._resource_id, {})

    #def _generate_friendly_name(self):
    #    name = self.resource.get("name", "Unbekannt")
    #    return f"{name} Switch ({self._resource_id})"

    @property
    def is_on(self):
        """Ermittelt den Status anhand der 'lastUsed'-Section."""
        last_used = self.resource.get("lastUsed")
        if last_used and last_used.get("id") and not last_used.get("stopType"):
            return True
        return False

    @property
    def device_info(self):
        """Erstellt das device_info-Dictionary mithilfe der Hilfsfunktion."""
        api_url = self.coordinator.api_url
        return get_device_info(self.resource, api_url)

    async def async_turn_on(self, **kwargs):
        """Schaltet die Maschine ein, indem die Fabman API aufgerufen wird."""
        await self._set_machine_status("on")

    async def async_turn_off(self, **kwargs):
        """Schaltet die Maschine aus, indem die Fabman API aufgerufen wird."""
        await self._set_machine_status("off")

    async def _set_machine_status_OLD(self, status):
        coordinator = self.coordinator
        api_url = coordinator.api_url
        api_token = coordinator.api_token

        if status == "on":
            endpoint = f"resources/{self._resource_id}/bridge/switch-on"
        elif status == "off":
            endpoint = f"resources/{self._resource_id}/bridge/switch-off"
        else:
            _LOGGER.error("Ungültiger Status: %s", status)
            return

        url = f"{api_url}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        session = async_get_clientsession(coordinator.hass)
        try:
            # Sende ein leeres JSON-Payload, falls die API dies erwartet.
            async with session.post(url, json={}, headers=headers) as response:
                if response.status != 201:
                    _LOGGER.error("Schalten der Bridge %s auf %s fehlgeschlagen: HTTP %s", self._resource_id, status, response.status)
                else:
                    _LOGGER.debug("Bridge %s erfolgreich auf %s geschaltet", self._resource_id, status)
        except Exception as e:
            _LOGGER.error("Fehler beim Schalten der Bridge %s: %s", self._resource_id, e)

    async def _set_machine_status(self, status):
        coordinator = self.coordinator
        api_url = coordinator.api_url
        api_token = coordinator.api_token

        if status == "on":
            endpoint = f"resources/{self._resource_id}/bridge/switch-on"
        elif status == "off":
            endpoint = f"resources/{self._resource_id}/bridge/switch-off"
        else:
            _LOGGER.error("Ungültiger Status: %s", status)
            return

        url = f"{api_url}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        session = async_get_clientsession(coordinator.hass)
        try:
            async with session.post(url, json={}, headers=headers) as response:
                if response.status != 201:
                    _LOGGER.error("Schalten der Bridge %s auf %s fehlgeschlagen: HTTP %s",
                                self._resource_id, status, response.status)
                else:
                    _LOGGER.debug("Bridge %s erfolgreich auf %s geschaltet", self._resource_id, status)
                    # Lokale Änderung: Erstelle eine Kopie der Ressource und setze den erwarteten Zustand.
                    resource = coordinator.data.get(self._resource_id, {}).copy()
                    if status == "on":
                        resource["lastUsed"] = {"id": "set_by_api", "stopType": None}
                    elif status == "off":
                        resource["lastUsed"] = {"id": None, "stopType": "set_by_api"}
                    # Aktualisiere die Daten im Koordinator und informiere alle Entitäten:
                    coordinator.data[self._resource_id] = resource
                    coordinator.async_set_updated_data(coordinator.data)
                    # Schreibe den neuen Zustand der Entität sofort:
                    self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Fehler beim Schalten der Bridge %s: %s", self._resource_id, e)
