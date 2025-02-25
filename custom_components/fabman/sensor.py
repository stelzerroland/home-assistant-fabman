import logging
import homeassistant.util.dt as dt_util  # 🔥 Import für Zeithandling
from datetime import timedelta  # 🔥 Import für Zeitdifferenzen
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
            continue  # Ignoriere Ressourcen ohne gültige Bridge-Daten
        entities.append(FabmanSensor(coordinator, resource_id))
    async_add_entities(entities)

class FabmanSensor(CoordinatorEntity, SensorEntity):
    """Sensor zur Anzeige des Maschinenstatus einer Fabman-Ressource."""

    def __init__(self, coordinator, resource_id):
        """Initialisiere den Sensor mit dem Coordinator und der Resource-ID."""
        super().__init__(coordinator)
        self._resource_id = resource_id
        self._attr_unique_id = f"fabman_resource_{resource_id}_status"  # Einmalig pro Gerät
        self._attr_entity_id = f"sensor.fabman_resource_{resource_id}"  # Entitäts-ID
        self._attr_name = f"{self.resource.get('name', 'Unbekannt')} Status"  # UI-Name
        #self._attr_name = self._generate_friendly_name()  # Fix für Namensprobleme

    #def _generate_friendly_name(self):
    #    """Erstellt einen konsistenten Friendly Name für den Sensor."""
    #    name = self.resource.get("name", f"Fabman Resource {self._resource_id}")
    #    return f"{name} Status"

    @property
    def resource(self):
        """Gibt die aktuellsten Daten für diese Ressource aus dem Coordinator zurück."""
        return self.coordinator.data.get(self._resource_id, {})

    @property
    def state(self):
        """Ermittelt den Zustand basierend auf 'lastUsed'-Daten und berücksichtigt Türen."""
        last_used = self.resource.get("lastUsed", None)

        # Falls `lastUsed` fehlt, Standardwert setzen
        if last_used is None:
            return "off"  # Maschine ist aus, wenn keine Nutzung erkannt wurde

        stop_type = last_used.get("stopType", None)
        control_type = self.resource.get("controlType", "")
        max_offline_usage = self.resource.get("maxOfflineUsage", 0)

        # Standardfall: Maschinenstatus anhand von stopType
        if control_type != "door":
            return "on" if stop_type is None else "off"

        # Spezialfall für Türen: Prüfe, ob die Tür noch offen ist
        last_used_time = last_used.get("at")
        if last_used_time:
            last_used_time = dt_util.parse_datetime(last_used_time)
            close_time = last_used_time + timedelta(seconds=max_offline_usage)
            if dt_util.utcnow() < close_time:
                return "on"  # Tür ist noch offen

        return "off"  # Tür oder Maschine ist aus


    @property
    def is_on(self):
        """Gibt True zurück, wenn der Zustand 'on' ist."""
        return self.state == "on"

    @property
    def device_info(self):
        """Erzeugt die device_info basierend auf den aktuellsten Ressourcendaten."""
        api_url = self.coordinator.api_url
        return get_device_info(self.resource, api_url)
