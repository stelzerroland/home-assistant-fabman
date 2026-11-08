"""Shared bridge commands for HA entities and authenticated direct links."""

import aiohttp
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .assignment import MemberAssignment, positive_id
from .lifecycle import resource_is_current


class CommandRejected(HomeAssistantError):
    """The server explicitly rejected this command."""


class CommandUncertain(HomeAssistantError):
    """The transport failed; acceptance is unknown."""


class AttributionUnconfirmed(HomeAssistantError):
    """Activation was accepted but its member could not be confirmed."""


class FabmanCommands:
    """One command implementation, with overridable session/assignment adapters."""

    def _command_session(self):
        return async_get_clientsession(self.coordinator.hass)

    def _member_assignment(self):
        return MemberAssignment(
            self._command_session(), self.coordinator, self._resource_id
        )

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

            assignment = self._member_assignment()
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
                raise AttributionUnconfirmed(
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
        # Only the dispatch phase is serialized; off never waits for attribution.
        async with self.coordinator.dispatch_locks[self._resource_id]:
            await self._async_send_command_unlocked(is_on, member_id=member_id)

    async def _async_send_command_unlocked(self, is_on, *, member_id=None):
        if not self.available:
            raise HomeAssistantError("Fabman resource is unavailable")
        if member_id is not None and (not is_on or not positive_id(member_id)):
            raise HomeAssistantError("Invalid Fabman member for switch-on")
        guard = getattr(self, "_before_send", None)
        if guard is not None:
            await guard()
        previous_resource = self.resource
        action = "switch-on" if is_on else "switch-off"
        url = (
            f"{self.coordinator.api_url.rstrip('/')}/resources/"
            f"{self._resource_id}/bridge/{action}"
        )
        headers = {"Authorization": f"Bearer {self.coordinator.api_token}"}
        session = self._command_session()
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
                    raise CommandRejected(
                        detail
                        or (
                            f"Fabman {action} failed for resource {self._resource_id}: "
                            f"HTTP {response.status}"
                        )
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CommandUncertain(
                f"Unable to control Fabman resource {self._resource_id}"
            ) from err

        command = self.coordinator.async_note_command(
            self._resource_id, is_on, previous_resource=previous_resource
        )
        sent = getattr(self, "_on_sent", None)
        if sent is not None:
            sent(command)


class ResourceCommands(FabmanCommands):
    """Entry-scoped commands without manufacturing an unregistered HA entity."""

    def __init__(self, coordinator, resource_id, before_send, on_sent):
        self.coordinator = coordinator
        self._resource_id = resource_id
        self._before_send = before_send
        self._on_sent = on_sent

    @property
    def resource(self):
        return (self.coordinator.data or {}).get(self._resource_id, {})

    @property
    def available(self):
        return (
            not self.coordinator._unloaded
            and self.coordinator.last_update_success
            and resource_is_current(self.resource)
            and self.resource.get("controlType") in ("machine", "door")
        )
