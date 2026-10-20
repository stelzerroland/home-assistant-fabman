"""Native API-reported resource activity for passive automation inputs."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .connectivity import bridge_is_connected
from .const import DOMAIN
from .entity import FabmanEntity
from .helpers import is_supported_resource


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        entity_class(coordinator, resource_id, config_entry.entry_id)
        for resource_id, resource in coordinator.data.items()
        if is_supported_resource(resource)
        for entity_class in (FabmanActivitySensor, FabmanConnectivitySensor)
    )


class FabmanActivitySensor(FabmanEntity, BinarySensorEntity):
    """Activity is not a command acknowledgement or a physical door contact."""

    _attr_has_entity_name = True
    _attr_name = "Activity"

    def __init__(self, coordinator, resource_id, entry_id):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_active_{entry_id}_{resource_id}"

    @property
    def device_class(self):
        if self.resource.get("controlType") == "machine":
            return BinarySensorDeviceClass.RUNNING
        return None

    @property
    def is_on(self):
        return self.coordinator.activity(self._resource_id).is_on

    @property
    def extra_state_attributes(self):
        activity = self.coordinator.activity(self._resource_id)
        return {
            "resource_id": self._resource_id,
            "resource_type": self.resource.get("controlType"),
            "status_source": activity.source,
            "status_reason": activity.reason,
        }


class FabmanConnectivitySensor(FabmanEntity, BinarySensorEntity):
    """Expose bridge connectivity independently of usage and command assumptions."""

    _attr_has_entity_name = True
    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, resource_id, entry_id):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_connectivity_{entry_id}_{resource_id}"

    @property
    def is_on(self):
        return bridge_is_connected(self.resource)

    @property
    def extra_state_attributes(self):
        connected = self.is_on
        return {
            "resource_id": self._resource_id,
            "status_source": "fabman_bridge",
            "status_reason": (
                "bridge_connectivity_unknown"
                if connected is None
                else "bridge_online"
                if connected
                else "bridge_offline"
            ),
        }
