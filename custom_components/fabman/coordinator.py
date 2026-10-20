"""Coordinate Fabman polling and delayed state updates."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
)
from .helpers import get_door_close_time, is_supported_resource
from .lifecycle import resource_is_current

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingCommand:
    """A requested state, separate from any observed resource data."""

    is_on: bool
    previous_door_grant: str | None = None


class FabmanDataUpdateCoordinator(DataUpdateCoordinator):
    """Fetch resources and own all timers for one config entry."""

    def __init__(self, hass, config):
        self.api_token = config[CONF_API_TOKEN]
        self.api_url = config.get(CONF_API_URL, DEFAULT_API_URL)
        self.enable_periodic_sync = config.get(
            CONF_ENABLE_PERIODIC_SYNC, DEFAULT_ENABLE_PERIODIC_SYNC
        )
        self.poll_interval = config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        self._session = async_get_clientsession(hass)
        self._door_timers = {}
        self._refresh_timers = {}
        self._unloaded = False
        self._revision = 0
        self._retry_not_before = 0
        self.pending_commands = {}
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
            resources = await FabmanAPI(
                self._session, self.api_url, self.api_token
            ).get_resources()
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
        self.last_successful_fetch = dt_util.utcnow()
        self.resource_count = len(resources)
        self.invalid_resource_count = invalid_count
        self.inventory_complete = invalid_count == 0
        self.supported_resource_count = sum(
            is_supported_resource(resource) for resource in new_data.values()
        )
        for resource_id, command in list(self.pending_commands.items()):
            resource = new_data.get(resource_id)
            matches = resource is not None and (
                evaluate_activity(resource).is_on is command.is_on
            )
            if matches and command.is_on and resource.get("controlType") == "door":
                # An old, still active release cannot acknowledge another opening.
                matches = resource["lastUsed"]["at"] != command.previous_door_grant
            if resource is None or not resource_is_current(resource) or matches:
                self.pending_commands.pop(resource_id)
        self._schedule_door_updates(new_data)
        return new_data

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
        return evaluate_activity((self.data or {}).get(resource_id))

    def async_set_updated_data(self, data):
        """Invalidate in-flight reads if newer confirmed data is supplied."""
        if self._unloaded:
            return
        self._revision += 1
        self.inventory_complete = False
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
            close_time = get_door_close_time(resource)
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

    def async_note_command(self, resource_id, is_on):
        """Record an accepted command without forging API usage or recovery."""
        # The resource may have disappeared while the command was in flight.
        if self._unloaded or not resource_is_current(self.data.get(resource_id)):
            return
        self._revision += 1
        resource = self.data[resource_id]
        usage = resource.get("lastUsed")
        previous_grant = (
            usage.get("at")
            if resource.get("controlType") == "door" and isinstance(usage, dict)
            else None
        )
        self.pending_commands[resource_id] = PendingCommand(is_on, previous_grant)
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
        for timers in (self._door_timers, self._refresh_timers):
            for timer in timers.values():
                timer.cancel()
            timers.clear()
