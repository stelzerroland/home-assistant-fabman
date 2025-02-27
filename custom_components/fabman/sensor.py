import logging
import homeassistant.util.dt as dt_util
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, CONF_API_URL
from .helpers import get_device_info

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setzt die Fabman Sensor-Plattform auf – nur für Ressourcen mit Bridge und passendem controlType."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []

    for resource_id, resource in coordinator.data.items():
        bridge_data = resource.get("_embedded", {}).get("bridge")  # Prüfen, ob eine Bridge existiert
        control_type = resource.get("controlType", "")  # Standardwert: leer
        max_offline_usage = resource.get("maxOfflineUsage", 0)  # Falls nicht definiert, auf 0 setzen
        name = resource.get("name", f"Fabman Resource {resource_id}")  # Falls Name fehlt, Standard setzen

        if bridge_data and control_type in ["machine", "door"]:
            entities.append(FabmanSensor(coordinator, resource_id, name, control_type, max_offline_usage))
            _LOGGER.info(f"✅ Sensor für {resource_id} ({control_type}) mit Bridge hinzugefügt.")
        else:
            _LOGGER.debug(f"❌ Sensor für {resource_id} nicht erstellt. "
                          f"Bridge vorhanden: {bool(bridge_data)}, controlType: {control_type}")

    async_add_entities(entities)



class FabmanSensor(CoordinatorEntity, SensorEntity):
    """Sensor zur Anzeige des Maschinenstatus einer Fabman-Ressource."""

    def __init__(self, coordinator, resource_id, name, control_type, max_offline_usage):
        """Initialisiere den Sensor mit dem Coordinator, Resource-ID und zusätzlichen Attributen."""
        super().__init__(coordinator)

        self._resource_id = resource_id
        self._control_type = control_type  # e.g., 'machine' or 'door'
        self._max_offline_usage = max_offline_usage  # Time a door stays 'open'
        self._attr_unique_id = f"fabman_sensor_{resource_id}"
        self._attr_name = f"{name} Status"
        self._attr_icon = "mdi:power"  # Default icon, can be changed
        self._attr_device_class = "power"  # Classifies as a power-related device
        self._attr_state_class = "measurement"  # Used for real-time monitoring

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

        # Standardfall: Maschinenstatus anhand von stopType
        if self._control_type != "door":
            return "on" if stop_type is None else "off"

        # Spezialfall für Türen: Prüfe, ob die Tür noch offen ist
        last_used_time = last_used.get("at")
        if last_used_time:
            last_used_time = dt_util.parse_datetime(last_used_time)
            close_time = last_used_time + timedelta(seconds=self._max_offline_usage)
            if dt_util.utcnow() < close_time:
                return "on"  # Tür ist noch offen

        return "off"  # Tür oder Maschine ist aus

    @property
    def is_on(self):
        """Gibt True zurück, wenn der Zustand 'on' ist."""
        return self.state == "on"

    @property
    def extra_state_attributes(self):
        """Zusätzliche Attribute für das Debugging in Home Assistant."""
        last_used = self.resource.get("lastUsed", {})
        return {
            "last_used_at": last_used.get("at", "Unknown"),
            "stop_type": last_used.get("stopType", "None"),
            "resource_type": self._control_type,
            "max_offline_usage": self._max_offline_usage
        }

    @property
    def device_info(self):
        """Erzeugt die device_info basierend auf den aktuellsten Ressourcendaten."""
        api_url = self.coordinator.api_url
        return get_device_info(self.resource, api_url)
