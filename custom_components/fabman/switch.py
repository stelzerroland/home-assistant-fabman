"""Switches for Fabman resources with a bridge."""

import aiohttp
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
        "switch",
        (
            lambda resource_id, resource: FabmanSwitch(
                coordinator, resource_id, resource["controlType"]
            ),
        ),
        async_add_entities,
    )


class FabmanSwitch(FabmanEntity, SwitchEntity):
    """Control a Fabman bridge."""

    def __init__(self, coordinator, resource_id, control_type):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_switch_{resource_id}"
        self._attr_name = self.resource.get("name", "Unknown")
        self._attr_device_class = "switch"

    @property
    def name(self):
        return self.resource_name

    @property
    def icon(self):
        return (
            "mdi:toggle-switch-variant"
            if self.is_on
            else "mdi:toggle-switch-variant-off"
        )

    @property
    def is_on(self):
        command = self.coordinator.pending_commands.get(self._resource_id)
        if command is not None:
            return command.is_on
        return self.coordinator.activity(self._resource_id).is_on

    @property
    def assumed_state(self):
        return self._resource_id in self.coordinator.pending_commands

    @property
    def extra_state_attributes(self):
        return {
            "resource_id": self._resource_id,
            "resource_state": self.resource_state,
            "state_source": (
                "command_assumption"
                if self.assumed_state
                else self.coordinator.activity(self._resource_id).source
            ),
        }

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

        self.coordinator.async_note_command(self._resource_id, is_on)
