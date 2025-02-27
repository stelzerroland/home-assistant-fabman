import logging
import aiohttp
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, CONF_API_URL
from .helpers import get_device_info
from datetime import datetime, timedelta
import homeassistant.util.dt as dt_util
import asyncio

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
<<<<<<< HEAD
        self._attr_unique_id = f"fabman_resource_{resource_id}"
        #self._attr_name = self._generate_friendly_name()
        self._attr_name = f"fabman_resource_{resource_id}"
=======
        self._attr_unique_id = f"fabman_resource_{resource_id}_switch"  # Einmalig pro Gerät
        self._attr_entity_id = f"switch.fabman_resource_{resource_id}"  # Entitäts-ID
        self._attr_name = f"{self.resource.get('name', 'Unbekannt')} Switch"  # UI-Name
>>>>>>> 38a02a0c9843b1090cb469f899585977dac19308

    @property
    def resource(self):
        """Gibt die aktuellen Daten der Ressource aus dem Coordinator zurück."""
        return self.coordinator.data.get(self._resource_id, {})

    #def _generate_friendly_name(self):
    #    name = self.resource.get("name", "Unbekannt")
    #    return f"{name} Switch ({self._resource_id})"

    @property
    def is_on(self):
        """Ermittelt den Status anhand der 'lastUsed'-Daten und berücksichtigt Türen."""
        last_used = self.resource.get("lastUsed", None)

        # Falls `lastUsed` fehlt, Standardwert setzen
        if last_used is None:
            return False  # Maschine ist aus, wenn keine Nutzung erkannt wurde

        stop_type = last_used.get("stopType", None)
        control_type = self.resource.get("controlType", "")
        max_offline_usage = self.resource.get("maxOfflineUsage", 0)

        # Standardfall: Maschinenstatus anhand von stopType
        if control_type != "door":
            return stop_type is None  # Falls kein stopType vorhanden ist, ist die Maschine an

        # Spezialfall für Türen: Prüfe, ob die Tür noch offen ist
        last_used_time = last_used.get("at")
        if last_used_time:
            last_used_time = dt_util.parse_datetime(last_used_time)
            close_time = last_used_time + timedelta(seconds=max_offline_usage)
            if dt_util.utcnow() < close_time:
                return True  # Tür ist noch offen

        return False  # Tür oder Maschine ist aus


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
                    #if status == "on":
                    #    resource["lastUsed"] = {"id": "set_by_api", "stopType": None}
                    #elif status == "off":
                    #    resource["lastUsed"] = {"id": None, "stopType": "set_by_api"}
                    if status == "on":
                        _LOGGER.info(f"🔄 Temporäres Setzen von {self._resource_id} auf 'on', bis API-Antwort kommt.")
                        resource["lastUsed"] = {"id": "temporary_on", "stopType": None}
                    elif status == "off":
                        _LOGGER.info(f"🔄 Temporäres Setzen von {self._resource_id} auf 'off', bis API-Antwort kommt.")
                        resource["lastUsed"] = {"id": None, "stopType": "temporary_off"}

                    # Aktualisiere die Daten im Koordinator
                    coordinator.data[self._resource_id] = resource
                    coordinator.async_set_updated_data(coordinator.data)

                    # Home Assistant Zustand sofort aktualisieren
                    self.async_write_ha_state()


                    # Auch den Sensor-Status aktualisieren, damit er direkt mit dem Schalter synchron ist
                    entity_registry = self.coordinator.hass.data.get("entity_registry")
                    sensor_entity_id = f"sensor.fabman_resource_{self._resource_id}"

                    # Falls der Sensor existiert, schreibe den neuen Zustand
                    if sensor_entity_id in self.coordinator.hass.states.async_entity_ids():
                        _LOGGER.info(f"🔄 Aktualisiere Sensor {sensor_entity_id} auf '{status}'")
                        self.coordinator.hass.states.async_set(sensor_entity_id, status)
                    else:
                        _LOGGER.warning(f"⚠️ Sensor {sensor_entity_id} nicht gefunden – kann nicht aktualisiert werden.")


                    # Starte einen neuen API-Refresh, damit auch die Sensoren neue Daten erhalten
                    _LOGGER.info(f"🕒 Warte ein paar Sekunden, bevor API-Refresh für Fabman Resource {self._resource_id} gestartet wird...")


                    # Prüfe, ob es sich um eine Tür handelt
                    control_type = self.resource.get("controlType", "")
                    max_offline_usage = self.resource.get("maxOfflineUsage", 0)

                    # Falls Tür: Warte "maxOfflineUsage" Sekunden + 2 Sekunden Puffer
                    if control_type == "door" and max_offline_usage > 0:
                        delay = max_offline_usage + 2
                        _LOGGER.info(f"🕒 Tür {self._resource_id} bleibt für {max_offline_usage} Sekunden 'on'. "
                                    f"Starte API-Refresh in {delay} Sekunden...")
                    else:
                        delay = 2  # Standard-Verzögerung für andere Geräte

                    await asyncio.sleep(delay)  # 🔥 Wartezeit setzen
                    await coordinator.async_refresh()
                    _LOGGER.info(f"🔄 API-Refresh für Fabman Resource {self._resource_id} abgeschlossen.")


                    await coordinator.async_refresh()
                    _LOGGER.info(f"🔄 API-Refresh für Fabman Resource {self._resource_id} abgeschlossen.")




        except Exception as e:
            _LOGGER.error("Fehler beim Schalten der Bridge %s: %s", self._resource_id, e)