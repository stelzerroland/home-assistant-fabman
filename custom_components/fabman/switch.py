"""Switches for Fabman resources with a bridge."""

import aiohttp
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .entity import FabmanEntity
from .helpers import resource_is_on


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up supported resources discovered during entry setup."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        FabmanSwitch(coordinator, resource_id, resource["controlType"])
        for resource_id, resource in coordinator.data.items()
        if (resource.get("_embedded") or {}).get("bridge")
        and resource.get("controlType") in ("machine", "door")
    )


class FabmanSwitch(FabmanEntity, SwitchEntity):
    """Control a Fabman bridge."""

    def __init__(self, coordinator, resource_id, control_type):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_switch_{resource_id}"
        self._attr_name = self.resource.get("name", "Unknown")
        self._attr_device_class = "switch"

    @property
    def icon(self):
        return (
            "mdi:toggle-switch-variant"
            if self.is_on
            else "mdi:toggle-switch-variant-off"
        )

    @property
    def is_on(self):
        return resource_is_on(self.resource)

    async def async_turn_on(self, **kwargs):
        await self._set_machine_status(True)

    async def async_turn_off(self, **kwargs):
        await self._set_machine_status(False)

    async def _set_machine_status(self, is_on):
        if not self.available:
            raise HomeAssistantError("Fabman resource is unavailable")
        action = "switch-on" if is_on else "switch-off"
        url = (
            f"{self.coordinator.api_url.rstrip('/')}/resources/"
            f"{self._resource_id}/bridge/{action}"
        )
        headers = {"Authorization": f"Bearer {self.coordinator.api_token}"}
        session = async_get_clientsession(self.coordinator.hass)
        try:
            async with session.post(url, json={}, headers=headers) as response:
                if response.status != 201:
                    raise HomeAssistantError(
                        f"Fabman {action} failed for resource {self._resource_id}: "
                        f"HTTP {response.status}"
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                f"Unable to control Fabman resource {self._resource_id}"
            ) from err

        self.coordinator.async_set_resource_status(self._resource_id, is_on)
