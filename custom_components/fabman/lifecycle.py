"""Resource lifecycle and dynamic entity discovery from accepted snapshots."""

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


def resource_is_current(resource):
    """Only current resources can be available or newly discovered."""
    return isinstance(resource, dict) and resource.get("state", "active") in (
        "active",
        "locked",
    )


def async_setup_discovery(
    hass, entry, coordinator, domain, factories, async_add_entities
):
    """Add each entity once; keep inactive registry entries for later reactivation."""
    from .helpers import is_supported_resource

    known = {}
    renamed_ids = {}

    @callback
    def registry_updated(event):
        old_id = event.data.get("old_entity_id")
        if old_id:
            for key, entity in known.items():
                if renamed_ids.get(key, entity.entity_id) == old_id:
                    renamed_ids[key] = event.data["entity_id"]
        if event.data["action"] == "remove":
            for key, entity in list(known.items()):
                if renamed_ids.get(key, entity.entity_id) == event.data["entity_id"]:
                    known.pop(key)
                    renamed_ids.pop(key, None)

    @callback
    def discover():
        if coordinator._unloaded or not coordinator.last_update_success:
            return
        added = []
        for resource_id, resource in (coordinator.data or {}).items():
            if not is_supported_resource(resource):
                continue
            for factory in factories:
                key = (resource_id, factory)
                if key in known:
                    continue
                entity = factory(resource_id, resource)
                if not resource_is_current(resource):
                    registry = er.async_get(hass)
                    entity_id = registry.async_get_entity_id(
                        domain, DOMAIN, entity.unique_id
                    )
                    registered = registry.async_get(entity_id) if entity_id else None
                    if (
                        registered is None
                        or registered.config_entry_id != entry.entry_id
                    ):
                        continue
                known[key] = entity
                added.append(entity)
        if added:
            async_add_entities(added)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))
    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_updated)
    )
