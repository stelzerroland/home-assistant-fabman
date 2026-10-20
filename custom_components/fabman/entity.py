"""Common availability and device information for Fabman entities."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .helpers import get_device_info


class FabmanEntity(CoordinatorEntity):
    """Keep missing resources unavailable and retain their device identity."""

    def __init__(self, coordinator, resource_id):
        super().__init__(coordinator)
        self._resource_id = resource_id
        self._attr_device_info = get_device_info(self.resource, coordinator.api_url)

    @property
    def resource(self):
        return (self.coordinator.data or {}).get(self._resource_id, {})

    @property
    def available(self):
        return super().available and self._resource_id in (self.coordinator.data or {})
