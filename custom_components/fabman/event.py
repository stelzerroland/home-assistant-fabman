"""POS authorization events observed in Fabman's resource log."""

from homeassistant.components.event import EventEntity
from homeassistant.core import callback

from .const import DOMAIN
from .entity import FabmanEntity
from .lifecycle import async_setup_discovery
from .presence import FabmanSpaceEntity, async_setup_space_discovery


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up one read-only authorization event entity per POS resource."""
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
