"""Coordinate Fabman polling and delayed state updates."""

import logging
from collections import defaultdict
from asyncio import Lock
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components import persistent_notification
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .activity import Activity, evaluate_activity
from .api import FabmanAPI, FabmanAPIError, FabmanRateLimitError
from .connectivity import bridge_is_connected
from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_ENABLE_PERIODIC_SYNC,
    CONF_POLL_INTERVAL,
    DEFAULT_API_URL,
    DEFAULT_ENABLE_PERIODIC_SYNC,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .helpers import get_door_close_time, is_supported_resource
from .lifecycle import resource_is_current
from .nuki import normalized_identifier, device_identifier
from .presence import PresenceTracker

_LOGGER = logging.getLogger(__name__)
COMMAND_CONFIRMATION_TIMEOUT = 30


def _aware_timestamp(value):
    """Parse only timezone-aware timestamps from API and storage data."""
    if not isinstance(value, str):
        return None
    try:
        parsed = dt_util.parse_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def _numeric_id(value):
    """Normalize a positive integer ID without accepting booleans or paths."""
    if type(value) is int and value > 0:
        return str(value)
    if (
        isinstance(value, str)
        and len(value) <= 20
        and value.isdecimal()
        and int(value) > 0
    ):
        return str(int(value))
    return None


@dataclass(frozen=True)
class PendingCommand:
    """A requested state, separate from any observed resource data."""

    is_on: bool
    previous_door_grant: str | None = None
    previous_door_usage_id: int | None = None


class FabmanDataUpdateCoordinator(DataUpdateCoordinator):
    """Fetch resources and own all timers for one config entry."""

    def __init__(self, hass, config, entry_id=None, user_member_map=None):
        self.api_token = config[CONF_API_TOKEN]
        self.api_url = config.get(CONF_API_URL, DEFAULT_API_URL)
        self.enable_periodic_sync = config.get(
            CONF_ENABLE_PERIODIC_SYNC, DEFAULT_ENABLE_PERIODIC_SYNC
        )
        self.poll_interval = config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        self._session = async_get_clientsession(hass)
        self._door_timers = {}
        self._refresh_timers = {}
        self._command_timeout_timers = {}
        self._unloaded = False
        self._revision = 0
        self._retry_not_before = 0
        self.pending_commands = {}
        self.timed_out_commands = {}
        self._entry_id = entry_id or "default"
        self.command_locks = defaultdict(Lock)
        self._assigned_door_grants = {}
        self._nuki_devices_by_space = {}
        self._nuki_failed_spaces = set()
        self.presence = PresenceTracker()
        configured_map = user_member_map if isinstance(user_member_map, dict) else {}
        self.user_member_map = {
            user_id: member_id
            for user_id, member_id in configured_map.items()
            if isinstance(user_id, str)
            and type(member_id) is int
            and 0 < member_id <= 2147483647
        }
        self.last_activations = {}
        self._activation_event_listeners = defaultdict(set)
        self._pos_event_listeners = defaultdict(set)
        self._pending_pos_events = defaultdict(list)
        self._pos_cursors = {}
        self._pos_seen_ids = defaultdict(set)
        self._pos_cursors_loaded = False
        self._pos_cursor_store = (
            Store(hass, 1, f"{DOMAIN}_{entry_id}_pos_cursors")
            if entry_id is not None
            else None
        )
        self.last_successful_fetch = None
        self.resource_count = 0
        self.invalid_resource_count = 0
        self.supported_resource_count = 0
        self.inventory_complete = False
        super().__init__(
            hass,
            _LOGGER,
            name="Fabman Data Coordinator",
            update_interval=(
                timedelta(seconds=self.poll_interval)
                if self.enable_periodic_sync
                else None
            ),
        )
        self.data = {}

    async def _async_update_data(self):
        if self.hass.loop.time() < self._retry_not_before:
            raise UpdateFailed("Fabman rate limit cooldown active")
        revision = self._revision
        try:
            api = FabmanAPI(self._session, self.api_url, self.api_token)
            resources = await api.get_resources()
            if not isinstance(resources, list):
                raise FabmanAPIError("Fabman resource response is not a list")
            new_data = {}
            invalid_count = 0
            for resource in resources:
                if not isinstance(resource, dict):
                    invalid_count += 1
                    continue
                resource_id = resource.get("id")
                if type(resource_id) is not int or resource_id <= 0:
                    invalid_count += 1
                    continue
                if resource_id in new_data:
                    raise FabmanAPIError("Duplicate resource IDs in snapshot")
                new_data[resource_id] = resource
            if resources and not new_data:
                raise FabmanAPIError("Resource snapshot has no identifiable resources")
            await self._async_load_pos_cursors()
            nuki_devices, nuki_failed_spaces = await self._fetch_nuki_devices(
                api, new_data
            )
            pos_events, pos_cursors, pos_seen_ids = await self._fetch_pos_events(
                api, new_data
            )
            (
                presence_states,
                presence_events,
                presence_failures,
            ) = await self.presence.async_prepare(api, new_data, dt_util.utcnow())
        except Exception as err:
            if isinstance(err, FabmanRateLimitError):
                self._retry_not_before = self.hass.loop.time() + err.retry_after
            if self._unloaded or revision != self._revision:
                return self._discard_outdated_snapshot()
            message = (
                str(err) if isinstance(err, FabmanAPIError) else "Fabman fetch failed"
            )
            # Neither transport exceptions nor raw payloads belong in HA logs.
            raise UpdateFailed(message) from None
        if self._unloaded or revision != self._revision:
            return self._discard_outdated_snapshot()
        self._revision += 1
        self._nuki_devices_by_space = nuki_devices
        self._nuki_failed_spaces = nuki_failed_spaces
        self._pos_cursors = pos_cursors
        self._pos_seen_ids = defaultdict(set, pos_seen_ids)
        accepted_revision = self._revision
        await self._async_save_pos_cursors()
        if self._unloaded or accepted_revision != self._revision:
            return self._discard_outdated_snapshot()
        for event in pos_events:
            self._dispatch_pos_event(event)
        self.presence.spaces = presence_states
        for scope, error in presence_failures:
            if isinstance(error, FabmanRateLimitError):
                self._retry_not_before = max(
                    self._retry_not_before, self.hass.loop.time() + error.retry_after
                )
            _LOGGER.warning(
                "Fabman attendance read failed for space %s: %s", scope[1], error
            )
        for event in presence_events:
            # Deliver after the accepted coordinator snapshot and discovery update.
            self.hass.loop.call_soon(self.presence.dispatch, event)
        self.last_successful_fetch = dt_util.utcnow()
        self.resource_count = len(resources)
        self.invalid_resource_count = invalid_count
        self.inventory_complete = invalid_count == 0
        self.supported_resource_count = sum(
            is_supported_resource(resource) for resource in new_data.values()
        )
        self._reconcile_commands(new_data)
        self._schedule_door_updates(new_data)
        return new_data

    def _reconcile_commands(self, resources):
        """Clear pending or expired requests only on matching observations."""
        commands = {**self.timed_out_commands, **self.pending_commands}
        for resource_id, command in commands.items():
            resource = resources.get(resource_id)
            observed = evaluate_activity(self._activity_resource(resource_id, resource))
            matches = resource is not None and observed.is_on is command.is_on
            if (
                resource is not None
                and command.is_on
                and resource.get("controlType") in ("door", "nuki")
            ):
                usage = resource.get("lastUsed")
                # A short release can already be over when the snapshot arrives.
                # Its new successful grant still acknowledges the opening command.
                matches = (
                    observed.reason
                    in (
                        "door_release_active",
                        "door_release_expired",
                        "nuki_access_active",
                        "nuki_access_expired",
                    )
                    and isinstance(usage, dict)
                    and usage.get("type", "allowed") == "allowed"
                )
                if matches:
                    if command.previous_door_usage_id is not None:
                        matches = (
                            type(usage.get("id")) is int
                            and usage["id"] != command.previous_door_usage_id
                        )
                    else:
                        matches = usage["at"] != command.previous_door_grant
            if (
                resource is None
                or not resource_is_current(resource)
                or matches
                or resource.get("controlType") not in ("machine", "door", "nuki")
            ):
                self._clear_command(resource_id)

    def _clear_command(self, resource_id):
        self.pending_commands.pop(resource_id, None)
        self.timed_out_commands.pop(resource_id, None)
        timer = self._command_timeout_timers.pop(resource_id, None)
        if timer is not None:
            timer.cancel()
        persistent_notification.async_dismiss(
            self.hass, self._command_notification_id(resource_id)
        )

    def _command_notification_id(self, resource_id):
        return f"fabman_{self._entry_id}_command_timeout_{resource_id}"

    @callback
    def _command_timed_out(self, resource_id, command):
        """End optimistic waiting without inventing an observed state or retrying."""
        if self._unloaded or self.pending_commands.get(resource_id) is not command:
            return
        timer = self._command_timeout_timers.pop(resource_id, None)
        if timer is not None:
            timer.cancel()
        self.pending_commands.pop(resource_id)
        self.timed_out_commands[resource_id] = command
        _LOGGER.warning(
            "Fabman command for resource %s was not confirmed within %s seconds; "
            "state remains unknown and no command was retried or cancelled",
            resource_id,
            COMMAND_CONFIRMATION_TIMEOUT,
        )
        persistent_notification.async_create(
            self.hass,
            f"The command for Fabman resource {resource_id} was not confirmed "
            f"within {COMMAND_CONFIRMATION_TIMEOUT} seconds. Its state is unknown. "
            "No automatic retry or switch-off was sent. This local timeout does "
            "not cancel a command still pending at Fabman; check before retrying.",
            title="Fabman command not confirmed",
            notification_id=self._command_notification_id(resource_id),
        )
        # Keep any current API read: a later matching snapshot can still confirm it.
        self.async_update_listeners()

    def _discard_outdated_snapshot(self):
        """Keep newer data/command barriers and coalesce a follow-up read."""
        self.async_schedule_refresh(None, delay=0)
        if not self.last_update_success:
            raise UpdateFailed("Awaiting a current successful Fabman snapshot")
        return self.data

    def activity(self, resource_id):
        """Expose observed activity without substituting an assumed command state."""
        resource = (self.data or {}).get(resource_id)
        if not resource_is_current(resource):
            return Activity(None, "resource_inactive_or_missing", "fabman_resource")
        if resource_id in self.pending_commands:
            return Activity(None, "command_unconfirmed", "bridge_command")
        if resource_id in self.timed_out_commands:
            return Activity(None, "command_timeout", "bridge_command")
        return evaluate_activity(self._activity_resource(resource_id, resource))

    def _activity_resource(self, resource_id, resource):
        """Do not treat our log edit timestamp as another door release."""
        grant = self._assigned_door_grants.get(resource_id)
        if grant is None or not isinstance(resource, dict):
            return resource
        usage = resource.get("lastUsed")
        if (
            resource.get("controlType") not in ("door", "nuki")
            or not isinstance(usage, dict)
            or usage.get("id") != grant[0]
        ):
            return resource
        return {**resource, "lastUsed": {**usage, "at": grant[1]}}

    def async_note_assigned_door_grant(self, resource_id, log):
        """Retain the verified original grant time before changing its member."""
        if self._unloaded or self.data.get(resource_id, {}).get("controlType") not in (
            "door",
            "nuki",
        ):
            return
        self._assigned_door_grants[resource_id] = (log["id"], log["createdAt"])
        self._revision += 1
        self._schedule_door_updates(self.data)
        self.async_update_listeners()

    def async_set_updated_data(self, data):
        """Invalidate in-flight reads if newer confirmed data is supplied."""
        if self._unloaded:
            return
        self._revision += 1
        self.inventory_complete = False
        self._reconcile_commands(data)
        self._schedule_door_updates(data)
        super().async_set_updated_data(data)

    def _schedule_door_updates(self, resources):
        """Update door states at expiry, even when polling is disabled."""
        for timer in self._door_timers.values():
            timer.cancel()
        self._door_timers.clear()
        if self._unloaded:
            return
        for resource_id, resource in resources.items():
            if (
                not resource_is_current(resource)
                or bridge_is_connected(resource) is not True
            ):
                continue
            close_time = get_door_close_time(
                self._activity_resource(resource_id, resource)
            )
            if close_time is None:
                continue
            delay = (close_time - dt_util.utcnow()).total_seconds()
            if delay > 0:
                self._door_timers[resource_id] = self.hass.loop.call_later(
                    delay, self._door_expired, resource_id
                )

    def _door_expired(self, resource_id):
        self._door_timers.pop(resource_id, None)
        if not self._unloaded:
            # Re-evaluate the release locally: Fabman sends no door off event.
            # Listener notification must not change API availability or raw usage.
            self.async_update_listeners()

    def async_note_command(self, resource_id, is_on, *, previous_resource=None):
        """Record an accepted command without forging API usage or recovery."""
        # The resource may have disappeared while the command was in flight.
        if self._unloaded or not resource_is_current(self.data.get(resource_id)):
            return
        self._revision += 1
        resource = (
            previous_resource
            if previous_resource is not None
            else self.data[resource_id]
        )
        usage = resource.get("lastUsed")
        previous_grant = (
            usage.get("at")
            if resource.get("controlType") in ("door", "nuki")
            and isinstance(usage, dict)
            else None
        )
        previous_usage_id = (
            usage.get("id")
            if resource.get("controlType") in ("door", "nuki")
            and isinstance(usage, dict)
            and type(usage.get("id")) is int
            else None
        )
        self._clear_command(resource_id)
        command = PendingCommand(is_on, previous_grant, previous_usage_id)
        self.pending_commands[resource_id] = command
        self._command_timeout_timers[resource_id] = self.hass.loop.call_later(
            COMMAND_CONFIRMATION_TIMEOUT, self._command_timed_out, resource_id, command
        )
        self.async_update_listeners()
        self.async_schedule_refresh(resource_id)

    def async_schedule_refresh(self, resource_id, delay=2):
        """Reconcile a command without delaying the service call."""
        if self._unloaded:
            return
        previous = self._refresh_timers.pop(resource_id, None)
        if previous is not None:
            previous.cancel()
        self._refresh_timers[resource_id] = self.hass.loop.call_later(
            delay, self._refresh_resource, resource_id
        )

    def _refresh_resource(self, resource_id):
        self._refresh_timers.pop(resource_id, None)
        if not self._unloaded:
            self.hass.async_create_task(self.async_request_refresh())

    def async_cancel_pending_updates(self):
        """Cancel callbacks when this entry is unloaded or setup fails."""
        self._unloaded = True
        self.pending_commands.clear()
        self.timed_out_commands.clear()
        self._assigned_door_grants.clear()
        self._pos_event_listeners.clear()
        self._activation_event_listeners.clear()
        self.last_activations.clear()
        self._pending_pos_events.clear()
        self.presence.close()
        for timers in (
            self._door_timers,
            self._refresh_timers,
            self._command_timeout_timers,
        ):
            for timer in timers.values():
                timer.cancel()
            timers.clear()

    def nuki_space_available(self, resource):
        """Return whether the latest Nuki device list for this space succeeded."""
        space_id = resource.get("space") if isinstance(resource, dict) else None
        key = _numeric_id(space_id)
        if key is None:
            return False
        return (
            key in self._nuki_devices_by_space and key not in self._nuki_failed_spaces
        )

    def nuki_device(self, resource):
        """Find the Nuki status record linked to one Fabman resource."""
        if not isinstance(resource, dict):
            return None
        space_id = _numeric_id(resource.get("space"))
        nuki_id = normalized_identifier(resource.get("nukiDeviceId"))
        if space_id is None or nuki_id is None:
            return None
        devices = self._nuki_devices_by_space.get(space_id, {})
        return devices.get(nuki_id)

    @callback
    def add_pos_event_listener(self, resource_id, listener):
        """Subscribe to new POS authorization events for one resource."""
        listeners = self._pos_event_listeners[resource_id]
        listeners.add(listener)
        for event in self._pending_pos_events.pop(resource_id, []):
            listener(event)

        @callback
        def remove_listener():
            listeners.discard(listener)
            if not listeners:
                self._pos_event_listeners.pop(resource_id, None)

        return remove_listener

    @callback
    def add_activation_event_listener(self, resource_id, listener):
        """Subscribe to accepted Home Assistant activation events."""
        listeners = self._activation_event_listeners[resource_id]
        listeners.add(listener)

        @callback
        def remove_listener():
            listeners.discard(listener)
            if not listeners:
                self._activation_event_listeners.pop(resource_id, None)

        return remove_listener

    @callback
    def async_note_activation(self, resource_id, event):
        """Keep the latest accepted activation and notify event/sensor entities."""
        if self._unloaded:
            return
        activation = {**event, "resource_id": resource_id}
        self.last_activations[resource_id] = activation
        for listener in tuple(self._activation_event_listeners.get(resource_id, ())):
            listener(activation)
        self.async_update_listeners()

    async def _async_load_pos_cursors(self):
        """Restore POS log watermarks without replaying history on first setup."""
        if self._pos_cursors_loaded:
            return
        self._pos_cursors_loaded = True
        if self._pos_cursor_store is None:
            return
        try:
            saved = await self._pos_cursor_store.async_load()
        except Exception:
            _LOGGER.warning("Unable to restore POS event cursors")
            return
        if not isinstance(saved, dict):
            return
        resources = saved.get("resources")
        if not isinstance(resources, dict):
            return
        for resource_id, record in resources.items():
            if not isinstance(record, dict):
                continue
            cursor = _aware_timestamp(record.get("cursor"))
            if cursor is None:
                continue
            self._pos_cursors[str(resource_id)] = cursor
            seen = record.get("seen", [])
            if isinstance(seen, list):
                self._pos_seen_ids[str(resource_id)] = {
                    value for value in seen if type(value) is int and value > 0
                }

    async def _async_save_pos_cursors(self):
        """Persist resource IDs, timestamps and log IDs without member data."""
        if self._pos_cursor_store is None:
            return
        try:
            await self._pos_cursor_store.async_save(
                {
                    "resources": {
                        resource_id: {
                            "cursor": cursor.isoformat(),
                            "seen": sorted(self._pos_seen_ids.get(resource_id, set()))[
                                -2000:
                            ],
                        }
                        for resource_id, cursor in self._pos_cursors.items()
                    }
                }
            )
        except Exception:
            _LOGGER.warning("Unable to save POS event cursors")

    async def _fetch_nuki_devices(self, api, resources):
        """Read each linked Fabman space once; isolate telemetry failures."""
        spaces = {
            space_id
            for resource in resources.values()
            if resource.get("controlType") == "nuki"
            and resource_is_current(resource)
            and is_supported_resource(resource)
            and (space_id := _numeric_id(resource.get("space"))) is not None
        }
        devices_by_space = {}
        failed_spaces = set()
        for space_id in spaces:
            try:
                devices = await api.get_nuki_devices(space_id)
                if not isinstance(devices, list):
                    raise FabmanAPIError("Fabman Nuki response is not a list")
            except FabmanAPIError as err:
                failed_spaces.add(space_id)
                if isinstance(err, FabmanRateLimitError):
                    self._retry_not_before = max(
                        self._retry_not_before,
                        self.hass.loop.time() + err.retry_after,
                    )
                _LOGGER.warning(
                    "Fabman Nuki status read failed for space %s: %s", space_id, err
                )
                continue
            mapped = {}
            for device in devices:
                identifier = device_identifier(device)
                if identifier is not None:
                    mapped[identifier] = device
            devices_by_space[space_id] = mapped
        return devices_by_space, failed_spaces

    async def _fetch_pos_events(self, api, resources):
        """Catch up allowed POS logs incrementally and omit personal fields."""
        now = dt_util.utcnow()
        cursors = dict(self._pos_cursors)
        seen_ids = {
            resource_id: set(values)
            for resource_id, values in self._pos_seen_ids.items()
        }
        events = []
        current_pos_ids = {
            str(resource_id)
            for resource_id, resource in resources.items()
            if resource.get("controlType") == "pos"
            and resource_is_current(resource)
            and is_supported_resource(resource)
        }
        for resource_id in set(cursors) - current_pos_ids:
            # Do not replay logs accumulated while a POS resource was inactive.
            cursors.pop(resource_id, None)
            seen_ids.pop(resource_id, None)
        for resource_id, resource in resources.items():
            if (
                resource.get("controlType") != "pos"
                or not resource_is_current(resource)
                or not is_supported_resource(resource)
            ):
                continue
            key = str(resource_id)
            cursor = cursors.get(key)
            if cursor is None:
                # Do not replay the POS's historical activity on first setup.
                cursors[key] = now
                seen_ids.setdefault(key, set())
                continue
            from_time = (cursor - timedelta(seconds=1)).isoformat()
            try:
                logs = await api.get_resource_logs(resource_id, from_time)
                if not isinstance(logs, list):
                    raise FabmanAPIError("Fabman POS log response is not a list")
            except FabmanAPIError as err:
                if isinstance(err, FabmanRateLimitError):
                    self._retry_not_before = max(
                        self._retry_not_before,
                        self.hass.loop.time() + err.retry_after,
                    )
                _LOGGER.warning(
                    "Fabman POS log read failed for resource %s: %s", resource_id, err
                )
                continue
            ids = seen_ids.setdefault(key, set())
            newest = cursor
            accepted = []
            for log in logs:
                if (
                    not isinstance(log, dict)
                    or log.get("resource") != resource_id
                    or log.get("account", resource.get("account"))
                    != resource.get("account")
                    or log.get("type") != "allowed"
                    or type(log.get("id")) is not int
                    or log["id"] <= 0
                ):
                    continue
                created_at = _aware_timestamp(log.get("createdAt"))
                if (
                    created_at is None
                    or created_at.tzinfo is None
                    or created_at > now
                    or created_at < cursor - timedelta(seconds=1)
                    or log["id"] in ids
                ):
                    continue
                accepted.append((created_at, log))
            for created_at, log in sorted(
                accepted, key=lambda item: (item[0], item[1]["id"])
            ):
                ids.add(log["id"])
                newest = max(newest, created_at)
                events.append(
                    {
                        "id": log["id"],
                        "resource": resource_id,
                        "type": "allowed",
                        "createdAt": log.get("createdAt"),
                        "stoppedAt": log.get("stoppedAt")
                        if isinstance(log.get("stoppedAt"), str)
                        else None,
                        "stopType": log.get("stopType")
                        if isinstance(log.get("stopType"), str)
                        else None,
                    }
                )
            cursors[key] = max(now, newest)
            if len(ids) > 2000:
                ids.intersection_update(
                    log["id"]
                    for log in logs
                    if isinstance(log, dict)
                    and type(log.get("id")) is int
                    and log.get("resource") == resource_id
                )
        return events, cursors, seen_ids

    @callback
    def _dispatch_pos_event(self, event):
        """Keep events pending until the matching HA entity is listening."""
        listeners = self._pos_event_listeners.get(event["resource"])
        if listeners:
            for listener in tuple(listeners):
                listener(event)
        else:
            self._pending_pos_events[event["resource"]].append(event)
