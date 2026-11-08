"""Switches for Fabman resources with a bridge."""

import aiohttp
import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.util import dt as dt_util

from .assignment import (
    MemberAssignment,
    positive_id,
)
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


class FabmanSwitch(FabmanEntity, SwitchEntity):
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

    async def async_turn_on_for_member(
        self, member_id=None, email_address=None, user_id=None
    ):
        """Activate with mapped or explicit member attribution when requested."""
        if user_id is not None:
            mapped_member_id = self.coordinator.user_member_map.get(user_id)
            if mapped_member_id is None:
                attribution = "api_key_user"
                target_kind = None
            else:
                attribution = "ha_user_mapping"
                target_kind = "mapped"
        elif member_id is not None or email_address is not None:
            attribution = "explicit_member"
            target_kind = "explicit"
        else:
            attribution = "api_key_user"
            target_kind = None

        user = None
        if user_id is not None:
            try:
                user = await self.coordinator.hass.auth.async_get_user(user_id)
            except Exception:
                user = None
        actor = {
            "ha_user_id": user_id,
            "ha_user_name": (
                user.name
                if user is not None and user.name
                else (
                    "Unknown Home Assistant user"
                    if user_id is not None
                    else "Home Assistant automation/service"
                )
            ),
            "attribution": attribution,
        }

        async with self.coordinator.command_locks[self._resource_id]:
            if not self.available:
                raise HomeAssistantError("Fabman resource is unavailable")

            if target_kind is None:
                await self._async_send_command(True)
                activation_time = dt_util.utcnow().isoformat()
                self.coordinator.async_note_activation(
                    self._resource_id,
                    {
                        **actor,
                        "occurred_at": activation_time,
                        "assignment_status": "not_requested",
                        "requested_member_id": None,
                        "assigned_member_id": None,
                    },
                )
                return

            assignment = MemberAssignment(
                async_get_clientsession(self.coordinator.hass),
                self.coordinator,
                self._resource_id,
            )
            if target_kind == "mapped":
                resolved_member_id = await assignment.resolve_member(
                    member_id=mapped_member_id
                )
            else:
                resolved_member_id = await assignment.resolve_member(
                    member_id=member_id,
                    email_address=email_address,
                )

            # Read a fresh baseline; do not attribute an already-running session.
            resource = await assignment.request("GET", f"resources/{self._resource_id}")
            if (
                not isinstance(resource, dict)
                or resource.get("id") != self._resource_id
                or resource.get("account") != assignment.account
                or resource.get("state") not in ("active", "locked")
                or resource.get("controlType") not in ("machine", "door", "nuki")
            ):
                raise HomeAssistantError("Fabman resource could not be verified")
            usage = resource.get("lastUsed")
            if usage is not None and not isinstance(usage, dict):
                raise HomeAssistantError("Invalid Fabman usage baseline")
            if isinstance(usage, dict) and (
                not positive_id(usage.get("id"))
                or (
                    resource.get("controlType") == "machine"
                    and not usage.get("stopType")
                )
            ):
                raise HomeAssistantError("Fabman usage is active or cannot be verified")
            baseline_id = usage.get("id") if usage else None
            direct_activation_started_at = dt_util.utcnow()
            await self._async_send_command(True, member_id=resolved_member_id)
            activation_time = dt_util.utcnow().isoformat()
            try:
                await assignment.confirm_direct_member(
                    resolved_member_id,
                    baseline_id,
                    direct_activation_started_at,
                )
            except (HomeAssistantError, TimeoutError):
                self.coordinator.async_note_activation(
                    self._resource_id,
                    {
                        **actor,
                        "occurred_at": activation_time,
                        "assignment_status": "failed",
                        "requested_member_id": resolved_member_id,
                        "assigned_member_id": None,
                    },
                )
                # Activation is never repeated or reversed on an attribution error.
                raise HomeAssistantError(
                    "Fabman activation was accepted, but member attribution could "
                    "not be confirmed. The resource may be on; check its activity "
                    "log. Do not repeat activation just to retry attribution."
                ) from None
            self.coordinator.async_note_activation(
                self._resource_id,
                {
                    **actor,
                    "occurred_at": activation_time,
                    "assignment_status": "assigned",
                    "requested_member_id": resolved_member_id,
                    "assigned_member_id": resolved_member_id,
                },
            )
            await self.coordinator.async_request_refresh()

    async def _async_send_command(self, is_on, *, member_id=None):
        if not self.available:
            raise HomeAssistantError("Fabman resource is unavailable")
        if member_id is not None and (not is_on or not positive_id(member_id)):
            raise HomeAssistantError("Invalid Fabman member for switch-on")
        previous_resource = self.resource
        action = "switch-on" if is_on else "switch-off"
        url = (
            f"{self.coordinator.api_url.rstrip('/')}/resources/"
            f"{self._resource_id}/bridge/{action}"
        )
        headers = {"Authorization": f"Bearer {self.coordinator.api_token}"}
        session = async_get_clientsession(self.coordinator.hass)
        try:
            async with session.post(
                url,
                json={"member": member_id} if member_id is not None else {},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,
            ) as response:
                if response.status != 201:
                    detail = None
                    if is_on and response.status == 422:
                        try:
                            error_body = await response.json()
                        except (aiohttp.ClientError, ValueError, TimeoutError):
                            error_body = None
                        if isinstance(error_body, dict):
                            data = error_body.get("data")
                            if isinstance(data, dict) and data.get("noPackage") is True:
                                detail = (
                                    "Fabman denied switch-on: the member used for "
                                    "this action has no package that allows access "
                                    "to this resource at this time."
                                )
                            elif (
                                isinstance(data, dict)
                                and data.get("noPermission") is True
                            ):
                                detail = (
                                    "Fabman denied switch-on: the member used for "
                                    "this action does not have permission to use "
                                    "this resource at this time."
                                )
                            elif (
                                isinstance(error_body.get("message"), str)
                                and error_body["message"].strip().casefold()
                                == "invalid member id"
                            ):
                                detail = (
                                    "Fabman rejected the member ID. Check the Home "
                                    "Assistant user mapping or the member_id passed "
                                    "to fabman.turn_on."
                                )
                    raise HomeAssistantError(
                        detail
                        or (
                            f"Fabman {action} failed for resource {self._resource_id}: "
                            f"HTTP {response.status}"
                        )
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                f"Unable to control Fabman resource {self._resource_id}"
            ) from err

        self.coordinator.async_note_command(
            self._resource_id, is_on, previous_resource=previous_resource
        )
