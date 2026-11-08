"""Switches for Fabman resources with a bridge."""

import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_register_platform_entity_service

from .assignment import (
    MemberAssignment,
)
from .commands import FabmanCommands
from .const import DOMAIN
from .entity import FabmanEntity
from .lifecycle import async_setup_discovery


async def _async_turn_on_service(entity, call):
    """Pass the authenticated caller and optional member selector to the switch."""
    await entity.async_turn_on_for_member(
        member_id=call.data.get("member_id"),
        email_address=call.data.get("email_address"),
        user_id=call.context.user_id,
    )


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up supported resources discovered during entry setup."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    if not hass.services.has_service(DOMAIN, "turn_on"):
        async_register_platform_entity_service(
            hass,
            DOMAIN,
            "turn_on",
            entity_domain="switch",
            schema={
                vol.Exclusive("member_id", "member"): vol.All(
                    int, vol.Range(min=1, max=2147483647)
                ),
                vol.Exclusive("email_address", "member"): vol.All(
                    str, vol.Length(min=3, max=255)
                ),
            },
            func=_async_turn_on_service,
        )
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
        resource_filter=lambda resource: (
            resource.get("controlType") in ("machine", "door", "nuki")
        ),
    )


class FabmanSwitch(FabmanCommands, FabmanEntity, SwitchEntity):
    """Control a Fabman bridge."""

    def __init__(self, coordinator, resource_id, control_type):
        super().__init__(coordinator, resource_id)
        self._attr_unique_id = f"fabman_switch_{resource_id}"
        self._attr_name = self.resource.get("name", "Unknown")
        self._attr_device_class = "switch"

    @property
    def available(self):
        return super().available and self.resource.get("controlType") in (
            "machine",
            "door",
            "nuki",
        )

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
        # HA sets _context immediately before invoking an entity service.
        context = getattr(self, "_context", None)
        await self.async_turn_on_for_member(
            user_id=getattr(context, "user_id", None)
        )

    async def async_turn_off(self, **kwargs):
        # A pending attribution must never delay an explicit stop request.
        await self._async_send_command(False)

    def _command_session(self):
        return async_get_clientsession(self.coordinator.hass)

    def _member_assignment(self):
        return MemberAssignment(
            self._command_session(), self.coordinator, self._resource_id
        )
