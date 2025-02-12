# Verzeichnis für die Integration erstellen
mkdir -p custom_components\my_integration

# Dateien erstellen und mit Basisinhalt füllen
Set-Content custom_components\my_integration\__init__.py @"
"""Minimal-Integration für Home Assistant."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "my_integration"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setzt die Integration mit einer Konfigurationsinstanz auf."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entfernt eine Konfigurationsinstanz."""
    hass.data[DOMAIN].pop(entry.entry_id)
    return True
"@

Set-Content custom_components\my_integration\manifest.json @"
{
  "domain": "my_integration",
  "name": "My Integration",
  "documentation": "https://github.com/YOUR_GITHUB_USERNAME/home-assistant-my-integration",
  "dependencies": [],
  "codeowners": ["@YOUR_GITHUB_USERNAME"],
  "requirements": [],
  "version": "1.0.0"
}
"@

Set-Content custom_components\my_integration\const.py @"
"""Globale Konstanten für die Integration."""
DOMAIN = "my_integration"
"@

Set-Content custom_components\my_integration\sensor.py @"
from homeassistant.helpers.entity import Entity
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    """Setzt die Sensor-Plattform auf."""
    async_add_entities([MyIntegrationSensor()])

class MyIntegrationSensor(Entity):
    """Ein Sensor, der 'Hello World' zurückgibt."""

    def __init__(self):
        """Initialisiert den Sensor."""
        self._attr_name = "My Sensor"
        self._attr_state = "unknown"

    @property
    def state(self):
        """Gibt den Sensorwert zurück."""
        return self._attr_state

    async def async_update(self):
        """Aktualisiert den Sensorwert."""
        self._attr_state = "Hello World"
"@

# Bestätigung ausgeben
Write-Host "Minimalintegration für Home Assistant wurde erfolgreich erstellt!"
