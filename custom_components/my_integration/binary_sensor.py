"""Binary Sensor für Fabman Bridges."""
import re
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN  # Domain aus der const.py

_LOGGER = logging.getLogger(__name__)


def sanitize_name(name: str) -> str:
    """Entferne Sonderzeichen aus dem Namen."""
    # Erlaubt sind Buchstaben, Zahlen, Unterstrich, Bindestrich und Leerzeichen.
    return re.sub(r"[^\w\s-]", "", name).strip()


class FabmanBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Repräsentiert einen Fabman Bridge Binary Sensor."""

    def __init__(self, coordinator, resource_id):
        """Initialisiere den Sensor für eine spezifische Ressource."""
        super().__init__(coordinator)
        self.resource_id = resource_id
        self._attr_unique_id = f"fabman_bridge_{resource_id}"
        # Der Name wird dynamisch aus den aktuellen Daten abgeleitet
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
            # Entferne evtl. Sonderzeichen im Namen
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
        # Wenn lastUsed vorhanden ist und ein "id" enthält und kein "stopType" (z. B. None oder nicht gesetzt) vorliegt,
        # gilt die Maschine als eingeschaltet.
        if last_used and last_used.get("id") and not last_used.get("stopType"):
            return True
        return False

    @property
    def available(self) -> bool:
        """Gebe an, ob das Gerät noch vorhanden ist."""
        # Falls die Resource nicht mehr in den Koordinator-Daten vorhanden ist, markieren wir den Sensor als nicht verfügbar.
        return self.resource is not None


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

    # Für die dynamische Hinzufügung neuer Geräte registrieren wir einen Listener
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
