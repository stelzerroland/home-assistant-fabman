"""Read-only, space-scoped attendance snapshots and session transitions."""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import FabmanAPIError, FabmanNotFoundError, FabmanRateLimitError
from .const import DOMAIN
from .helpers import get_base_url, is_supported_resource
from .lifecycle import resource_is_current

OVERLAP = timedelta(seconds=60)


def positive_id(value):
    return type(value) is int and value > 0


def timestamp(value):
    if not isinstance(value, str):
        raise FabmanAPIError("Invalid Fabman check-in timestamp")
    try:
        parsed = dt_util.parse_datetime(value)
    except (ValueError, TypeError, OverflowError):
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise FabmanAPIError("Invalid Fabman check-in timestamp")
    return parsed


@dataclass(frozen=True)
class CheckInSession:
    id: int
    member_id: int
    member_name: str
    resource_id: int
    started: datetime
    ended: datetime | None
    stop_type: str | None


def parse_session(log, account_id):
    """Keep only attendance fields; never retain full member profiles."""
    if not isinstance(log, dict) or log.get("type") != "checkIn":
        raise FabmanAPIError("Invalid Fabman check-in record")
    member = log.get("member")
    resource = log.get("resource")
    member_id = member.get("id") if isinstance(member, dict) else member
    resource_id = resource.get("id") if isinstance(resource, dict) else resource
    if (
        not all(positive_id(value) for value in (log.get("id"), member_id, resource_id))
        or type(log.get("account")) is not int
        or log["account"] != account_id
        or (
            isinstance(member, dict) and member.get("account", account_id) != account_id
        )
    ):
        raise FabmanAPIError("Invalid Fabman check-in identity or account")
    name = (
        " ".join(
            value.strip()
            for key in ("firstName", "lastName")
            if isinstance(member, dict)
            and isinstance(value := member.get(key), str)
            and value.strip()
        )
        or f"Member {member_id}"
    )
    started = timestamp(log.get("createdAt"))
    ended = timestamp(log["stoppedAt"]) if log.get("stoppedAt") is not None else None
    stop_type = log.get("stopType")
    if (
        (ended is not None and ended < started)
        or (stop_type is not None and (not isinstance(stop_type, str) or not stop_type))
        or (ended is None and stop_type is not None)
    ):
        raise FabmanAPIError("Invalid Fabman check-in completion")
    return CheckInSession(
        log["id"], member_id, name, resource_id, started, ended, stop_type
    )


def parse_sessions(logs, account_id):
    if not isinstance(logs, list):
        raise FabmanAPIError("Invalid Fabman check-in list")
    result = {}
    for log in logs:
        session = parse_session(log, account_id)
        if session.id in result:
            raise FabmanAPIError("Duplicate Fabman check-in records")
        result[session.id] = session
    return result


@dataclass(frozen=True)
class SpacePresence:
    account_id: int
    space_id: int
    name: str
    active: bool = True
    available: bool = False
    sessions: dict = field(default_factory=dict)
    seen: dict = field(default_factory=dict)
    cursor: datetime | None = None
    baseline: datetime | None = None
    last_successful_sync: datetime | None = None

    @property
    def members(self):
        """Count people, not sessions, and keep their earliest open check-in."""
        grouped = {}
        for session in sorted(
            self.sessions.values(), key=lambda item: (item.started, item.id)
        ):
            member = grouped.setdefault(
                session.member_id,
                {
                    "member_id": session.member_id,
                    "name": session.member_name,
                    "checked_in_at": session.started.isoformat(),
                    "resource_ids": [],
                },
            )
            if session.resource_id not in member["resource_ids"]:
                member["resource_ids"].append(session.resource_id)
        return sorted(
            grouped.values(),
            key=lambda item: (item["name"].casefold(), item["member_id"]),
        )


class PresenceTracker:
    """Prepare changes transactionally; a rejected coordinator read changes nothing."""

    def __init__(self):
        self.spaces = {}
        self._listeners = defaultdict(set)
        self._closed = False

    async def async_prepare(self, api, resources, now):
        scopes = {
            (resource["account"], resource["space"])
            for resource in resources.values()
            if resource.get("controlType") == "checkIn"
            and is_supported_resource(resource)
            and resource_is_current(resource)
            and positive_id(resource.get("account"))
            and positive_id(resource.get("space"))
        }
        states = {
            key: replace(value, active=False, available=False)
            for key, value in self.spaces.items()
        }
        events, failures = [], []
        for scope in sorted(scopes):
            previous = self.spaces.get(scope)
            if previous is None or not previous.active:
                previous = SpacePresence(*scope, name=f"Space {scope[1]}")
            try:
                state, transitions = await self._fetch_space(
                    api, previous, now, resources
                )
            except FabmanAPIError as err:
                states[scope] = replace(previous, active=True, available=False)
                failures.append((scope, err))
            else:
                states[scope] = state
                events.extend(transitions)
        return states, events, failures

    async def _fetch_space(self, api, previous, now, resources):
        account_id, space_id = previous.account_id, previous.space_id
        name = previous.name
        if name == f"Space {space_id}":
            try:
                space = await api.get_space(space_id)
                if (
                    space.get("id") == space_id
                    and space.get("account") == account_id
                    and isinstance(space.get("name"), str)
                    and space["name"].strip()
                ):
                    name = space["name"].strip()
            except FabmanRateLimitError:
                raise
            except FabmanAPIError:
                # A missing space label does not invalidate its attendance data.
                pass
        recent = {}
        if previous.cursor is not None:
            recent = parse_sessions(
                await api.get_check_in_logs(
                    account_id,
                    space_id,
                    status="all",
                    from_time=(previous.cursor - OVERLAP).isoformat(),
                ),
                account_id,
            )
        active = parse_sessions(
            await api.get_check_in_logs(account_id, space_id), account_id
        )
        for session in (*recent.values(), *active.values()):
            resource = resources.get(session.resource_id)
            if resource is not None and (
                resource.get("account") != account_id
                or resource.get("space") != space_id
            ):
                raise FabmanAPIError(
                    "Fabman check-in resource belongs to another space"
                )
        if any(session.ended is not None for session in active.values()):
            raise FabmanAPIError("Completed session in active Fabman check-ins")
        if previous.cursor is None:
            # Rebuild presence on every setup; never replay pre-start attendance.
            return replace(
                previous,
                name=name,
                available=True,
                active=True,
                sessions=active,
                cursor=now,
                baseline=now,
                seen={
                    (sid, "checked_in"): item.started for sid, item in active.items()
                },
                last_successful_sync=now,
            ), []

        candidates = {**recent, **active}
        missing = (
            set(previous.sessions)
            | {sid for sid, session in recent.items() if session.ended is None}
        ) - active.keys()
        for session_id in sorted(missing):
            try:
                session = parse_session(
                    await api.get_check_in_log(session_id), account_id
                )
            except FabmanNotFoundError:
                # Removal is a reconciliation, never an invented checkout.
                candidates.pop(session_id, None)
                continue
            resource = resources.get(session.resource_id)
            if resource is not None and (
                resource.get("account") != account_id
                or resource.get("space") != space_id
            ):
                # A log moved to another space is a correction, not a departure.
                candidates.pop(session_id, None)
                continue
            if session.id != session_id or session.ended is None:
                raise FabmanAPIError("Inconsistent Fabman check-in snapshot")
            candidates[session_id] = session
        seen = dict(previous.seen)
        for session in previous.sessions.values():
            seen.setdefault((session.id, "checked_in"), session.started)
        events = []
        for session in candidates.values():
            for event_type, occurred_at in (
                ("checked_in", session.started),
                ("checked_out", session.ended),
            ):
                token = (session.id, event_type)
                if (
                    occurred_at is None
                    or token in seen
                    or occurred_at < previous.baseline
                    or occurred_at < previous.cursor - OVERLAP
                    or (event_type == "checked_in" and session.id in previous.sessions)
                ):
                    continue
                seen[token] = occurred_at
                events.append(
                    {
                        "event_type": event_type,
                        "account_id": account_id,
                        "space_id": space_id,
                        "member_id": session.member_id,
                        "member_name": session.member_name,
                        "resource_id": session.resource_id,
                        "log_id": session.id,
                        "occurred_at": occurred_at.isoformat(),
                        "observed_at": dt_util.utcnow().isoformat(),
                        "stop_type": session.stop_type
                        if event_type == "checked_out"
                        else None,
                    }
                )
        seen = {token: at for token, at in seen.items() if at >= now - OVERLAP}
        events.sort(
            key=lambda event: (
                timestamp(event["occurred_at"]),
                event["log_id"],
                event["event_type"] == "checked_out",
            )
        )
        return replace(
            previous,
            name=name,
            active=True,
            available=True,
            sessions=active,
            seen=seen,
            cursor=now,
            last_successful_sync=now,
        ), events

    @callback
    def add_listener(self, scope, listener):
        self._listeners[scope].add(listener)

        @callback
        def remove():
            self._listeners[scope].discard(listener)
            if not self._listeners[scope]:
                self._listeners.pop(scope, None)

        return remove

    @callback
    def dispatch(self, event):
        if not self._closed:
            scope = (event["account_id"], event["space_id"])
            for listener in tuple(self._listeners.get(scope, ())):
                listener(event)

    def close(self):
        self._closed = True
        self._listeners.clear()


class FabmanSpaceEntity(CoordinatorEntity):
    """Attendance entities belong to a space service, independently of bridges."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, scope, entry_id, suffix):
        super().__init__(coordinator)
        self.scope = scope
        self._attr_unique_id = f"fabman_{suffix}_{entry_id}_{scope[0]}_{scope[1]}"
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, f"fabman_presence_{scope[0]}_{scope[1]}")},
            name=f"Fabman – {self.snapshot.name}",
            manufacturer="Fabman",
            model="Space attendance",
            entry_type=dr.DeviceEntryType.SERVICE,
            configuration_url=f"{get_base_url(coordinator.api_url)}/manage/{scope[0]}",
        )

    @property
    def snapshot(self):
        return self.coordinator.presence.spaces.get(self.scope)

    @property
    def available(self):
        state = self.snapshot
        return (
            super().available and state is not None and state.active and state.available
        )

    def _handle_coordinator_update(self):
        if self.snapshot is not None:
            name = f"Fabman – {self.snapshot.name}"
            self._attr_device_info = {**self._attr_device_info, "name": name}
            if self.registry_entry and self.registry_entry.device_id:
                registry = dr.async_get(self.hass)
                device = registry.async_get(self.registry_entry.device_id)
                if device and device.name != name:
                    registry.async_update_device(device.id, name=name)
        super()._handle_coordinator_update()


def async_setup_space_discovery(
    hass, entry, coordinator, domain, factory, async_add_entities
):
    known = {}
    renamed_ids = {}

    @callback
    def registry_updated(event):
        old_id = event.data.get("old_entity_id")
        if old_id:
            for scope, entity in known.items():
                if renamed_ids.get(scope, entity.entity_id) == old_id:
                    renamed_ids[scope] = event.data["entity_id"]
        if event.data["action"] == "remove":
            for scope, entity in list(known.items()):
                if renamed_ids.get(scope, entity.entity_id) == event.data["entity_id"]:
                    known.pop(scope)
                    renamed_ids.pop(scope, None)

    @callback
    def discover():
        if coordinator._unloaded or not coordinator.last_update_success:
            return
        added = []
        registry = er.async_get(hass)
        for scope, state in coordinator.presence.spaces.items():
            if scope in known:
                continue
            entity = factory(coordinator, scope, entry.entry_id)
            if not state.active:
                entity_id = registry.async_get_entity_id(
                    domain, DOMAIN, entity.unique_id
                )
                registered = registry.async_get(entity_id) if entity_id else None
                if registered is None or registered.config_entry_id != entry.entry_id:
                    continue
            known[scope] = entity
            added.append(entity)
        if added:
            async_add_entities(added)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))
    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_updated)
    )
