"""Status sensors for Fabman resources."""

from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN
from .entity import FabmanEntity
from .lifecycle import async_setup_discovery


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up supported resources discovered during entry setup."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_setup_discovery(
        hass,
        config_entry,
        coordinator,
        "sensor",
        (
            lambda resource_id, resource: FabmanSensor(
                coordinator,
                resource_id,
                resource.get("name", f"Fabman Resource {resource_id}"),
                resource["controlType"],
                resource.get("maxOfflineUsage", 0),
            ),
        ),
        async_add_entities,
    )


class FabmanSensor(FabmanEntity, SensorEntity):
    """Expose the existing on/off status without numeric measurement metadata."""

    def __init__(self, coordinator, resource_id, name, control_type, max_offline_usage):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_sensor_{resource_id}"
        self._attr_name = f"{name} Status"

    @property
    def name(self):
        return f"{self.resource_name} Status"

    @property
    def icon(self):
        if self.resource.get("controlType") == "door":
            return "mdi:door-open" if self.is_on else "mdi:door-closed"
        return "mdi:power-plug" if self.is_on else "mdi:power-plug-off"

    @property
    def native_value(self):
        if self.is_on is None:
            return None
        return "on" if self.is_on else "off"

    @property
    def is_on(self):
        return self.coordinator.activity(self._resource_id).is_on

    @property
    def extra_state_attributes(self):
        last_used = self.resource.get("lastUsed")
        if not isinstance(last_used, dict):
            last_used = {}
        activity = self.coordinator.activity(self._resource_id)
        return {
            "resource_id": self._resource_id,
            "resource_state": self.resource_state,
            "status_source": activity.source,
            "status_reason": activity.reason,
            "last_used_at": last_used.get("at", "Unknown"),
            "stop_type": last_used.get("stopType", "None"),
            "resource_type": self.resource.get("controlType"),
            "max_offline_usage": self.resource.get("maxOfflineUsage", 0),
        }
