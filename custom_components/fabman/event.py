"""Events published by Fabman resource activity."""

from homeassistant.components.event import EventEntity
from homeassistant.core import callback

from .const import DOMAIN
from .entity import FabmanEntity
from .lifecycle import async_setup_discovery
from .presence import FabmanSpaceEntity, async_setup_space_discovery


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up read-only Fabman event entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_setup_space_discovery(
        hass,
        config_entry,
        coordinator,
        "event",
        FabmanCheckInActivityEvent,
        async_add_entities,
    )
    async_setup_discovery(
        hass,
        config_entry,
        coordinator,
        "event",
        (
            lambda resource_id, resource: FabmanPOSEvent(
                coordinator, resource_id, config_entry.entry_id
            ),
        ),
        async_add_entities,
        resource_filter=lambda resource: resource.get("controlType") == "pos",
    )
    async_setup_discovery(
        hass,
        config_entry,
        coordinator,
        "event",
        (
            lambda resource_id, resource: FabmanActivationEvent(
                coordinator, resource_id, config_entry.entry_id
            ),
        ),
        async_add_entities,
        resource_filter=lambda resource: (
            resource.get("controlType") in ("machine", "door", "nuki")
        ),
    )


class FabmanCheckInActivityEvent(FabmanSpaceEntity, EventEntity):
    """Attendance transitions with the affected Fabman member, scoped to a space."""

    _attr_name = "Check-in activity"
    _attr_event_types = ["checked_in", "checked_out"]
    _attr_icon = "mdi:account-arrow-right"

    def __init__(self, coordinator, scope, entry_id):
        super().__init__(coordinator, scope, entry_id, "check_in_activity")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.presence.add_listener(self.scope, self._event)
        )

    @callback
    def _event(self, event):
        if not self.available:
            return
        self._trigger_event(
            event["event_type"],
            {key: value for key, value in event.items() if key != "event_type"},
        )
        self.async_write_ha_state()


class FabmanPOSEvent(FabmanEntity, EventEntity):
    """Fire an event when Fabman records an allowed POS authorization."""

    _attr_has_entity_name = True
    _supported_control_types = ("pos",)
    _attr_name = "Authorization"
    _attr_event_types = ["authorized"]

    def __init__(self, coordinator, resource_id, entry_id):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_pos_authorization_{entry_id}_{resource_id}"
        self._remove_pos_event_listener = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_pos_event_listener = self.coordinator.add_pos_event_listener(
            self._resource_id, self._handle_pos_event
        )

    async def async_will_remove_from_hass(self):
        if self._remove_pos_event_listener is not None:
            self._remove_pos_event_listener()
            self._remove_pos_event_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_pos_event(self, log):
        """Publish only non-personal fields from the Fabman usage log."""
        if (
            not isinstance(log, dict)
            or log.get("resource") != self._resource_id
            or log.get("type") != "allowed"
            or type(log.get("id")) is not int
        ):
            return
        attributes = {
            "resource_id": self._resource_id,
            "log_id": log["id"],
            "created_at": log.get("createdAt"),
            "stopped_at": log.get("stoppedAt"),
            "stop_type": log.get("stopType"),
        }
        self._trigger_event("authorized", attributes)
        self.async_write_ha_state()


class FabmanActivationEvent(FabmanEntity, EventEntity):
    """Record who requested an accepted activation in Home Assistant."""

    _attr_has_entity_name = True
    _supported_control_types = ("machine", "door", "nuki")
    _attr_name = "Activation"
    _attr_icon = "mdi:account-key"
    _attr_event_types = ["activated"]

    def __init__(self, coordinator, resource_id, entry_id):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_activation_{entry_id}_{resource_id}"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.add_activation_event_listener(
                self._resource_id, self._handle_activation
            )
        )

    @callback
    def _handle_activation(self, event):
        """Publish the HA actor and whether member reassignment completed."""
        if not self.available or not isinstance(event, dict):
            return
        attributes = {
            key: event.get(key)
            for key in (
                "resource_id",
                "occurred_at",
                "ha_user_id",
                "ha_user_name",
                "attribution",
                "assignment_status",
                "requested_member_id",
                "assigned_member_id",
            )
        }
        self._trigger_event("activated", attributes)
        self.async_write_ha_state()
