"""Status sensors for Fabman resources."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)

from .const import DOMAIN
from .entity import FabmanEntity
from .lifecycle import async_setup_discovery
from .nuki import battery_level
from .presence import FabmanSpaceEntity, async_setup_space_discovery


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up supported resources discovered during entry setup."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_setup_space_discovery(
        hass,
        config_entry,
        coordinator,
        "sensor",
        FabmanCheckedInMembersSensor,
        async_add_entities,
    )
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
        resource_filter=lambda resource: (
            resource.get("controlType") in ("machine", "door", "nuki")
        ),
    )
    async_setup_discovery(
        hass,
        config_entry,
        coordinator,
        "sensor",
        (
            lambda resource_id, resource: FabmanNukiBatterySensor(
                coordinator, resource_id, config_entry.entry_id
            ),
        ),
        async_add_entities,
        resource_filter=lambda resource: resource.get("controlType") == "nuki",
    )


class FabmanCheckedInMembersSensor(FabmanSpaceEntity, SensorEntity):
    """Current API-reported membership, deduplicated across terminals in a space."""

    _attr_name = "Checked-in members"
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator, scope, entry_id):
        super().__init__(coordinator, scope, entry_id, "checked_in_members")

    @property
    def native_value(self):
        return len(self.snapshot.members) if self.available else None

    @property
    def extra_state_attributes(self):
        state = self.snapshot
        return {
            "account_id": self.scope[0],
            "space_id": self.scope[1],
            "members": state.members if state is not None else [],
            "active_sessions": len(state.sessions) if state is not None else None,
            "last_successful_sync": state.last_successful_sync.isoformat()
            if state is not None and state.last_successful_sync is not None
            else None,
        }


class FabmanSensor(FabmanEntity, SensorEntity):
    """Expose the existing on/off status without numeric measurement metadata."""

    _supported_control_types = ("machine", "door", "nuki")

    def __init__(self, coordinator, resource_id, name, control_type, max_offline_usage):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_sensor_{resource_id}"
        self._attr_name = f"{name} Status"

    @property
    def name(self):
        return f"{self.resource_name} Status"

    @property
    def icon(self):
        if self.resource.get("controlType") in ("door", "nuki"):
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


class FabmanNukiBatterySensor(FabmanEntity, SensorEntity):
    """Expose the Nuki battery percentage provided by Fabman."""

    _attr_has_entity_name = True
    _supported_control_types = ("nuki",)
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, resource_id, entry_id):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_nuki_battery_{entry_id}_{resource_id}"

    @property
    def available(self):
        return super().available and self.coordinator.nuki_space_available(
            self.resource
        )

    @property
    def native_value(self):
        return battery_level(self.coordinator.nuki_device(self.resource))

    @property
    def extra_state_attributes(self):
        device = self.coordinator.nuki_device(self.resource)
        state = device.get("state") if isinstance(device, dict) else None
        return {
            "resource_id": self._resource_id,
            "battery_critical": (
                state.get("batteryCritical") if isinstance(state, dict) else None
            ),
            "status_source": "fabman_nuki",
        }
