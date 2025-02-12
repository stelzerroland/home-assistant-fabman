"""Binary Sensor für Fabman Bridges."""
import re
import logging
from urllib.parse import urljoin

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN  # Domain aus der const.py

_LOGGER = logging.getLogger(__name__)


def sanitize_name(name: str) -> str:
    """Entferne Sonderzeichen aus dem Namen.
    
    Erlaubt sind Buchstaben, Zahlen, Unterstrich, Bindestrich und Leerzeichen.
    """
    return re.sub(r"[^\w\s-]", "", name).strip()


class FabmanBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Repräsentiert einen Fabman Bridge Binary Sensor, der einem Device zugeordnet ist."""

    def __init__(self, coordinator, resource_id):
        """Initialisiere den Sensor für eine spezifische Ressource."""
        super().__init__(coordinator)
        self.resource_id = resource_id
        self._attr_unique_id = f"fabman_bridge_{resource_id}"
        self._name = None

    @property
    def resource(self):
        """Hole die zugehörige Resource aus den Koordinator-Daten."""
        if self.coordinator.data:
            for res in self.coordinator.data:
                if res.get("id") == self.resource_id:
                    return res
        return None

    @property
    def name(self):
        """Gebe den Namen des Sensors zurück."""
        res = self.resource
        if res:
            # Bereinige evtl. Sonderzeichen im Namen
            name = res.get("name", "Unbekannt")
            self._name = f"{sanitize_name(name)} ({self.resource_id})"
            return self._name
        return f"Fabman Bridge {self.resource_id}"

    @property
    def is_on(self):
        """Berechne den Zustand anhand der lastUsed-Daten."""
        res = self.resource
        if not res:
            return False

        last_used = res.get("lastUsed")
        # Wenn lastUsed vorhanden ist, ein "id" gesetzt ist und kein "stopType" vorliegt,
        # gilt die Maschine als eingeschaltet.
        if last_used and last_used.get("id") and not last_used.get("stopType"):
            return True
        return False

    @property
    def available(self) -> bool:
        """Gebe an, ob die Ressource noch vorhanden ist."""
        return self.resource is not None


#    @property
#    def device_info(self):
#        """Gebe Informationen zum Device (Fabman Bridge) zurück, damit HA die Entität einem Device zuordnet."""
#        res = self.resource or {}
#        return {
#            "identifiers": {(DOMAIN, self.resource_id)},
#            "name": self.name,
#            "manufacturer": "Fabman",
#            "model": res.get("type", "Unbekannt"),  # Hier könnte der Typ oder ein anderer Wert als Modell genutzt werden
#            "sw_version": str(res.get("targetFirmware", "n/a")),  # Optional: Firmware-Version als String
#        }

    @property
    def device_info(self):
        """Gebe Informationen zur Fabman Bridge zurück, inklusive Seriennummer (falls vorhanden)."""
        res = self.resource or {}
        embedded = res.get("_embedded", {})
        bridge = embedded.get("bridge")  # Kann `None` oder `{}` sein

        if bridge is None:
            _LOGGER.info("Keine Bridge-Daten für Gerät %s gefunden.", self.resource_id)
            bridge = {}  # Falls `None`, setzen wir ein leeres Dictionary, um Fehler zu vermeiden

        return {
            "identifiers": {(DOMAIN, bridge.get("serialNumber", f"fabman_{self.resource_id}"))},
            "name": self.name,
            "manufacturer": "Fabman",
            "model": bridge.get("hardwareVersion", res.get("type", "Unbekannt")),  # Nutze Fallback
            "sw_version": bridge.get("firmwareVersion", str(res.get("targetFirmware", "n/a"))),
            "configuration_url": f"https://fabman.io/resources/{self.resource_id}",
        }


async def async_setup_entry(hass, entry, async_add_entities):
    """Setze die Binary Sensor Plattform für Fabman auf."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = {}

    # Initial: Erstelle für jede vorhandene Resource einen Sensor
    for res in coordinator.data or []:
        resource_id = res.get("id")
        if resource_id is not None:
            sensors[resource_id] = FabmanBinarySensor(coordinator, resource_id)

    async_add_entities(list(sensors.values()), True)

    # Registriere einen Listener für dynamisch hinzugekommene Ressourcen
    def update_new_entities():
        known_ids = set(sensors.keys())
        new_entities = []
        for res in coordinator.data or []:
            res_id = res.get("id")
            if res_id is not None and res_id not in known_ids:
                _LOGGER.debug("Neues Fabman-Gerät gefunden: %s", res_id)
                sensor = FabmanBinarySensor(coordinator, res_id)
                sensors[res_id] = sensor
                new_entities.append(sensor)
        if new_entities:
            async_add_entities(new_entities, True)

    coordinator.async_add_listener(update_new_entities)
