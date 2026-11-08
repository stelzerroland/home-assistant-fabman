"""User-bound, opt-in confirmations. URLs themselves never authorize commands."""

import asyncio
from dataclasses import dataclass
from secrets import token_urlsafe

from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .assignment import MemberAssignment, positive_id
from .commands import (
    AttributionUnconfirmed,
    CommandRejected,
    CommandUncertain,
    ResourceCommands,
)
from .connectivity import bridge_is_connected
from .const import CONF_DIRECT_LINK_RESOURCES, CONF_USER_MEMBER_MAP, DOMAIN
from .lifecycle import resource_is_current

CONFIRMATION_TTL = 60
RESULT_TTL = 600
MAX_RECORDS = 256


class DirectLinkError(HomeAssistantError):
    """An error code safe to send to the authenticated frontend."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def enabled_resources(options):
    """Missing, malformed or newly discovered options always fail closed."""
    values = options.get(CONF_DIRECT_LINK_RESOURCES, [])
    if not isinstance(values, list):
        return set()
    return {value for value in values if positive_id(value)}


def resource_path(entry_id, resource_id):
    return f"/fabman/qr/{entry_id}/{resource_id}"


@dataclass
class Confirmation:
    user_id: str
    entry_id: str
    resource_id: int
    entity_id: str
    coordinator: object
    action: str
    fingerprint: tuple
    member_id: int | None
    created: float
    context: Context
    task: object = None
    phase: str = "prepared"
    command_id: str | None = None
    member_status: str = "not_requested"
    error: str | None = None


class DirectLinks:
    """Bounded in-memory intents and reconnectable results, scoped to HA users."""

    def __init__(self, hass):
        self.hass = hass
        self.entries = {}
        self.records = {}
        self.panel_registered = False
        self.static_registered = False

    def attach(self, entry):
        self.entries[entry.entry_id] = entry

    def detach(self, entry_id):
        self.entries.pop(entry_id, None)
        for record in self.records.values():
            if record.entry_id == entry_id:
                running = record.task is not None and not record.task.done()
                awaiting_command = (
                    record.phase == "accepted"
                    and record.command_id is not None
                    and record.coordinator.command_outcomes.get(record.command_id)
                    not in ("confirmed", "timeout", "superseded", "unavailable")
                )
                if record.phase != "prepared" and not running and not awaiting_command:
                    continue
                record.phase = "interrupted"
                record.error = "interrupted"
                if record.member_status == "pending":
                    record.member_status = "failed"
                if running:
                    record.task.cancel()

    def _user(self, user):
        if user is None or not user.is_active or user.system_generated:
            raise DirectLinkError("unauthorized")

    def _target(self, user, entry_id, resource_id):
        self._user(user)
        if not isinstance(entry_id, str) or not positive_id(resource_id):
            raise DirectLinkError("unavailable")
        entry = self.entries.get(entry_id)
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if (
            entry is None
            or entry.disabled_by is not None
            or coordinator is None
            or coordinator._unloaded
            or resource_id not in enabled_resources(entry.options)
        ):
            raise DirectLinkError("unavailable")
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "switch", DOMAIN, f"fabman_switch_{resource_id}"
        )
        entity = registry.async_get(entity_id) if entity_id else None
        if (
            entity is None
            or entity.config_entry_id != entry_id
            or entity.disabled
            or not user.permissions.check_entity(entity_id, POLICY_READ)
            or not user.permissions.check_entity(entity_id, POLICY_CONTROL)
        ):
            raise DirectLinkError("unauthorized")
        state = self.hass.states.get(entity_id)
        if state is None or state.state == "unavailable":
            raise DirectLinkError("unavailable")
        return coordinator, entity_id

    def _snapshot(self, coordinator, resource_id):
        resource = (coordinator.data or {}).get(resource_id)
        if (
            not coordinator.last_update_success
            or not resource_is_current(resource)
            or resource.get("controlType") not in ("machine", "door")
            or bridge_is_connected(resource) is not True
            or resource_id in coordinator.pending_commands
            or resource_id in coordinator.timed_out_commands
        ):
            raise DirectLinkError("unavailable")
        activity = coordinator.activity(resource_id)
        if resource["controlType"] == "machine" and activity.is_on is None:
            raise DirectLinkError("unknown_state")
        action = (
            "open"
            if resource["controlType"] == "door"
            else "off"
            if activity.is_on
            else "on"
        )
        usage = resource.get("lastUsed") or {}
        if not isinstance(usage, dict):
            raise DirectLinkError("unknown_state")
        fingerprint = (
            resource.get("account"),
            resource["controlType"],
            resource.get("state"),
            tuple(
                usage.get(key)
                for key in ("id", "at", "stopType", "stoppedAt", "lockVersion")
            ),
            action,
        )
        return resource, action, fingerprint

    def _member(self, coordinator, entry_id, user_id):
        configured = self.entries[entry_id].options.get(CONF_USER_MEMBER_MAP, {})
        configured = configured.get(user_id) if isinstance(configured, dict) else None
        configured = configured if positive_id(configured) else None
        # Options change before the automatic entry reload completes.
        if configured != coordinator.user_member_map.get(user_id):
            raise DirectLinkError("changed")
        return configured

    def _prune(self):
        now = self.hass.loop.time()
        for key, record in list(self.records.items()):
            if now - record.created > (
                CONFIRMATION_TTL if record.phase == "prepared" else RESULT_TTL
            ) and (record.task is None or record.task.done()):
                self.records.pop(key)

    async def prepare(self, user, entry_id, resource_id, context=None):
        self._prune()
        if len(self.records) >= MAX_RECORDS:
            raise DirectLinkError("busy")
        coordinator, entity_id = self._target(user, entry_id, resource_id)
        await coordinator.async_refresh()
        current, current_entity = self._target(user, entry_id, resource_id)
        if current is not coordinator or current_entity != entity_id:
            raise DirectLinkError("changed")
        resource, action, fingerprint = self._snapshot(coordinator, resource_id)
        member_id = self._member(coordinator, entry_id, user.id)
        member_name = None
        if member_id is not None and action != "off":
            assignment = MemberAssignment(
                coordinator._session, coordinator, resource_id
            )
            try:
                await assignment.resolve_member(member_id=member_id)
            except (HomeAssistantError, TimeoutError):
                raise DirectLinkError("invalid_mapping") from None
            member_name = assignment.member_name
        # The entry may have been disabled/reloaded while member data was read.
        if self._target(user, entry_id, resource_id) != (coordinator, entity_id):
            raise DirectLinkError("changed")
        if self._snapshot(coordinator, resource_id)[2] != fingerprint:
            raise DirectLinkError("changed")
        if self._member(coordinator, entry_id, user.id) != member_id:
            raise DirectLinkError("changed")
        if len(self.records) >= MAX_RECORDS:
            raise DirectLinkError("busy")
        key = token_urlsafe(24)
        self.records[key] = Confirmation(
            user.id,
            entry_id,
            resource_id,
            entity_id,
            coordinator,
            action,
            fingerprint,
            member_id,
            self.hass.loop.time(),
            context or Context(user_id=user.id),
        )
        return {
            "confirmation_id": key,
            "expires_in": CONFIRMATION_TTL,
            "name": resource.get("name", str(resource_id)),
            "resource_id": resource_id,
            "action": action,
            "is_on": coordinator.activity(resource_id).is_on,
            "observed_at": (
                coordinator.last_successful_fetch.isoformat()
                if coordinator.last_successful_fetch
                else None
            ),
            "member_id": member_id if action != "off" else None,
            "member_name": member_name,
            "ha_user_name": user.name,
        }

    def _owned(self, user, key):
        self._user(user)
        self._prune()
        record = self.records.get(key)
        if record is None or record.user_id != user.id:
            raise DirectLinkError("expired")
        if not user.permissions.check_entity(record.entity_id, POLICY_CONTROL):
            raise DirectLinkError("unauthorized")
        return record

    def execute(self, user, key):
        record = self._owned(user, key)
        if record.task is not None:
            return self.status(user, key)
        if record.phase != "prepared":
            raise DirectLinkError("expired")
        if self.hass.loop.time() - record.created > CONFIRMATION_TTL:
            raise DirectLinkError("expired")
        self._target(user, record.entry_id, record.resource_id)
        record.phase = "running"
        record.task = self.hass.async_create_background_task(
            self._run(record), f"Fabman direct link {record.resource_id}"
        )
        return self.status(user, key)

    async def _guard(self, record):
        user = await self.hass.auth.async_get_user(record.user_id)
        coordinator, entity_id = self._target(user, record.entry_id, record.resource_id)
        if (
            coordinator is not record.coordinator
            or entity_id != record.entity_id
            or self.hass.loop.time() - record.created > CONFIRMATION_TTL
        ):
            raise DirectLinkError("expired")
        await coordinator.async_refresh()
        # No await between final authorization/state check and command dispatch.
        if self._target(user, record.entry_id, record.resource_id) != (
            coordinator,
            entity_id,
        ):
            raise DirectLinkError("changed")
        if self.hass.loop.time() - record.created > CONFIRMATION_TTL:
            raise DirectLinkError("expired")
        if (
            self._snapshot(coordinator, record.resource_id)[2] != record.fingerprint
            or self._member(coordinator, record.entry_id, record.user_id)
            != record.member_id
        ):
            raise DirectLinkError("changed")

    async def _run(self, record):
        def sent(command):
            record.command_id = command.command_id if command else None
            record.phase = "accepted" if command else "uncertain"
            if command is None:
                record.error = "uncertain"
            record.member_status = (
                "pending"
                if record.member_id is not None and record.action != "off"
                else "not_requested"
            )

        executor = ResourceCommands(
            record.coordinator,
            record.resource_id,
            lambda: self._guard(record),
            sent,
        )
        try:
            await self._guard(record)
            if record.action == "off":
                await executor._async_send_command(False)
            else:
                await executor.async_turn_on_for_member(user_id=record.user_id)
                if record.member_status == "pending":
                    record.member_status = "assigned"
        except asyncio.CancelledError:
            record.phase, record.error = "interrupted", "interrupted"
            if record.member_status == "pending":
                record.member_status = "failed"
        except AttributionUnconfirmed:
            record.member_status, record.error = "failed", "attribution_unconfirmed"
        except CommandUncertain:
            record.phase, record.error = "uncertain", "uncertain"
        except CommandRejected:
            record.phase, record.error = "rejected", "rejected"
        except DirectLinkError as err:
            record.phase, record.error = "blocked", err.code
        except (HomeAssistantError, TimeoutError):
            record.error = "unavailable"
            if record.command_id is None:
                record.phase = "blocked"
        except Exception:
            # Never return transport exceptions, URLs or credentials to the UI.
            record.phase, record.error = "uncertain", "uncertain"

    def status(self, user, key):
        record = self._owned(user, key)
        command_status = None
        if record.command_id:
            coordinator = record.coordinator
            command_status = coordinator.command_outcomes.get(record.command_id)
            if command_status is None:
                pending = coordinator.pending_commands.get(record.resource_id)
                command_status = (
                    "pending"
                    if pending and pending.command_id == record.command_id
                    else "unknown"
                )
        return {
            "operation_id": key,
            "phase": record.phase,
            "action": record.action,
            "command_status": command_status,
            "member_status": record.member_status,
            "error": record.error,
        }

    def list_links(self, user):
        self._user(user)
        if not user.is_admin:
            raise DirectLinkError("unauthorized")
        links = []
        for entry_id, entry in self.entries.items():
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
            if coordinator is None:
                continue
            for resource_id in sorted(enabled_resources(entry.options)):
                resource = (coordinator.data or {}).get(resource_id, {})
                if resource_is_current(resource) and resource.get("controlType") in (
                    "machine",
                    "door",
                ):
                    links.append(
                        {
                            "name": resource.get("name", str(resource_id)),
                            "entry_title": entry.title,
                            "path": resource_path(entry_id, resource_id),
                        }
                    )
        return links
