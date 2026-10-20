"""Common availability and device information for Fabman entities."""

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .helpers import get_device_info
from .lifecycle import resource_is_current


class FabmanEntity(CoordinatorEntity):
    """Keep missing resources unavailable and retain their device identity."""

    def __init__(self, coordinator, resource_id):
        super().__init__(coordinator)
        self._resource_id = resource_id
        name = self.resource.get("name")
        self._resource_name = name if isinstance(name, str) and name else "Resource"
        self._attr_device_info = get_device_info(self.resource, coordinator.api_url)

    @property
    def resource(self):
        return (self.coordinator.data or {}).get(self._resource_id, {})

    @property
    def available(self):
        return super().available and resource_is_current(
            (self.coordinator.data or {}).get(self._resource_id)
        )

    @property
    def resource_name(self):
        name = self.resource.get("name")
        return name if isinstance(name, str) and name else self._resource_name

    @property
    def resource_state(self):
        if not self.resource:
            return "missing"
        state = self.resource.get("state", "active")
        return (
            state if state in ("active", "locked", "archived", "deleted") else "unknown"
        )

    def _handle_coordinator_update(self):
        if self.coordinator.last_update_success and self.resource:
            self._resource_name = self.resource_name
            self._attr_device_info = {
                **self._attr_device_info,
                "name": f"{self._resource_name} ({self._resource_id})",
            }
            if self.registry_entry and self.registry_entry.device_id:
                registry = dr.async_get(self.hass)
                device = registry.async_get(self.registry_entry.device_id)
                if device:
                    info = self._attr_device_info
                    if device.name != info["name"]:
                        registry.async_update_device(device.id, name=info["name"])
        super()._handle_coordinator_update()
