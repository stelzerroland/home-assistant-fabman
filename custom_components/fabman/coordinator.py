"""Coordinate Fabman polling and delayed state updates."""

import logging
from datetime import timedelta

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FabmanAPI
from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_ENABLE_PERIODIC_SYNC,
    CONF_POLL_INTERVAL,
    DEFAULT_API_URL,
    DEFAULT_ENABLE_PERIODIC_SYNC,
    DEFAULT_POLL_INTERVAL,
)
from .helpers import get_door_close_time

_LOGGER = logging.getLogger(__name__)


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
        try:
            resources = await FabmanAPI(
                self._session, self.api_url, self.api_token
            ).get_resources()
        except Exception as err:
            raise UpdateFailed(f"Error fetching Fabman resources: {err}") from err
        new_data = {
            resource["id"]: resource
            for resource in resources
            if resource.get("id") is not None
        }
        self._schedule_door_updates(new_data)
        return new_data

    def _schedule_door_updates(self, resources):
        """Update door states at expiry, even when polling is disabled."""
        for timer in self._door_timers.values():
            timer.cancel()
        self._door_timers.clear()
        if self._unloaded:
            return
        for resource_id, resource in resources.items():
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
            self.async_update_listeners()
            self.hass.async_create_task(self.async_request_refresh())

    def async_set_resource_status(self, resource_id, is_on):
        """Publish an optimistic state only after a successful command."""
        # The resource may have disappeared while the command was in flight.
        if self._unloaded or resource_id not in self.data:
            return
        resource = self.data[resource_id].copy()
        last_used = (resource.get("lastUsed") or {}).copy()
        last_used.update(
            at=dt_util.utcnow().isoformat(),
            stopType=None if is_on else "temporary_off",
        )
        resource["lastUsed"] = last_used
        new_data = {**self.data, resource_id: resource}
        self._schedule_door_updates(new_data)
        self.async_set_updated_data(new_data)
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
        for timers in (self._door_timers, self._refresh_timers):
            for timer in timers.values():
                timer.cancel()
            timers.clear()
