"""Binary Sensor für Fabman Bridges."""
import re
import logging
from urllib.parse import urljoin

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN  # Domain aus der const.py

_LOGGER = logging.getLogger(__name__)

def sanitize_name(name: str) -> str:
    """Entferne Sonderzeichen aus dem Namen."""
    return re.sub(r"[^\w\s-]", "", name).strip()

class FabmanBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Repräsentiert einen Fabman Bridge Binary Sensor."""

    def __init__(self, coordinator, resource_id):
        """Initialisiere den Sensor für eine spezifische Ressource."""
        super().__init__(coordinator)
        self.resource_id = resource_id

        # **Setze Unique-ID stabil auf die Fabman-ID (diese ändert sich NIE)**
        self._attr_unique_id = f"fabman_{resource_id}"

        # **Setze die entity_id explizit**
        self._attr_entity_id = f"binary_sensor.fabman_{resource_id}"

    @property
    def name(self):
        """Gebe den aktuellen Namen aus Fabman zurück (kann sich ändern)."""
        res = self.resource
        if res:
            return sanitize_name(res.get("name", f"Fabman {self.resource_id}"))
        return f"Fabman {self.resource_id}"
    
    @property
    def resource(self):
        """Hole die zugehörige Resource aus den Koordinator-Daten."""
        if self.coordinator.data:
            for res in self.coordinator.data:
                if res.get("id") == self.resource_id:
                    return res
        return None

    @property
    def is_on(self):
        """Berechne den Zustand anhand der lastUsed-Daten."""
        res = self.resource
        if not res:
            return False

        last_used = res.get("lastUsed")
        if last_used and last_used.get("id") and not last_used.get("stopType"):
            return True
        return False

    @property
    def available(self) -> bool:
        """Gebe an, ob die Ressource noch vorhanden ist."""
        return self.resource is not None

    @property
    def device_info(self):
        """Gebe Informationen zur Fabman Bridge zurück, mit sinnvollen Fallbacks falls Bridge-Daten fehlen."""
        res = self.resource or {}
        embedded = res.get("_embedded", {})
        bridge = embedded.get("bridge", {})

        if not isinstance(bridge, dict):
            _LOGGER.warning("Fehlende oder ungültige Brückendaten für Ressource %s, Fallback wird verwendet.", self.resource_id)
            bridge = {}

        # **Sinnvolle Fallbacks für eingeschränkte API-Rechte**
        device_id = bridge.get("serialNumber") or f"fabman_{self.resource_id}"
        model = res.get("type", "Unbekannt")  # Nutze den Maschinen-Typ als Modell
        firmware = str(res.get("targetFirmware", "n/a"))  # Falls `firmwareVersion` fehlt, nutze `targetFirmware`
        account_id = res.get("account", "1")  # Falls nicht vorhanden, Standardwert `1`

        # **Dynamische configuration_url basierend auf API-URL**
        base_url = "https://internal.fabman.io"
        if "fabman_api_url" in self.coordinator.hass.data[DOMAIN]:
            base_url = self.coordinator.hass.data[DOMAIN]["fabman_api_url"].rstrip("/")

        config_url = f"{base_url}/manage/{account_id}/configuration/resources/{self.resource_id}"

        # Falls device_id immer noch None ist, logge den Fehler und gib None zurück
        if not device_id:
            _LOGGER.error("Gerät %s hat keine gültige ID, wird nicht registriert!", self.name)
            return None

        # **Fix für `via_device`: Nutze `serialNumber`, falls vorhanden**
        via_device = (DOMAIN, bridge.get("serialNumber")) if bridge.get("serialNumber") else None

        _LOGGER.debug(
            "Registriere Gerät in HA: Name=%s, ID=%s, Model=%s, SW-Version=%s, Config-URL=%s, Via-Device=%s",
            self.name, device_id, model, firmware, config_url, via_device
        )

        return {
            "identifiers": {(DOMAIN, device_id)},
            "name": self.name,
            "manufacturer": "Fabman",
            "model": model,
            "sw_version": firmware,
            "configuration_url": config_url,
            "via_device": via_device,  # Jetzt mit tatsächlicher Geräte-ID oder None
        }


async def async_setup_entry(hass, entry, async_add_entities):
    """Setze die Binary Sensor Plattform für Fabman auf."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = {}

    for res in coordinator.data or []:
        resource_id = res.get("id")
        if resource_id is not None:
            sensors[resource_id] = FabmanBinarySensor(coordinator, resource_id)

    async_add_entities(list(sensors.values()), True)

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
