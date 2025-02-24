import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, CONF_API_URL
from .helpers import get_device_info

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Richtet die Sensor-Plattform ein – ein Sensor pro Fabman-Ressource, die Bridge-Daten besitzt."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    for resource_id, resource in coordinator.data.items():
        bridge_data = resource.get("_embedded", {}).get("bridge")
        if not bridge_data:
            # Ignoriere Ressourcen ohne gültige Bridge-Daten
            continue
        entities.append(FabmanSensor(coordinator, resource_id))
    async_add_entities(entities)

class FabmanSensor(CoordinatorEntity, SensorEntity):
    """Sensor zur Anzeige des Maschinenstatus einer Fabman-Ressource."""

    def __init__(self, coordinator, resource_id):
        """Initialisiere den Sensor mit dem Coordinator und der Resource-ID."""
        super().__init__(coordinator)
        self._resource_id = resource_id
        self._attr_unique_id = f"fabman_resource_{resource_id}_status"
        # Der Name wird dynamisch generiert, kann aber auch hier initial gesetzt werden.
        self._attr_name = f"Fabman {resource_id} Status"

    @property
    def resource(self):
        """Gibt die aktuellsten Daten für diese Ressource aus dem Coordinator zurück."""
        return self.coordinator.data.get(self._resource_id, {})

    def _generate_friendly_name(self):
        name = self.resource.get("name", "Unbekannt")
        return f"{name} Status ({self._resource_id})"

    @property
    def state(self):
        """Ermittelt den Zustand basierend auf den 'lastUsed'-Daten."""
        last_used = self.resource.get("lastUsed")
        if last_used and last_used.get("id") and not last_used.get("stopType"):
            return "on"
        return "off"

    @property
    def is_on(self):
        """Gibt True zurück, wenn der Zustand 'on' ist."""
        last_used = self.resource.get("lastUsed")
        if last_used and last_used.get("id") and not last_used.get("stopType"):
            return True
        return False

    @property
    def device_info(self):
        """Erzeugt die device_info basierend auf den aktuellsten Ressourcendaten."""
        api_url = self.coordinator.api_url
        return get_device_info(self.resource, api_url)
