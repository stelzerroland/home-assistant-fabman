"""Accepted commands expire independently of polling without controlling hardware."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components import persistent_notification
from homeassistant.util import dt as dt_util

from custom_components.fabman.api import FabmanAPIError
from custom_components.fabman.binary_sensor import FabmanActivitySensor
from custom_components.fabman.coordinator import COMMAND_CONFIRMATION_TIMEOUT
from custom_components.fabman.sensor import FabmanSensor
from custom_components.fabman.switch import FabmanSwitch

from .factories import machine


def resource(control_type="door", *, usage_id=10):
    result = machine(active=False)
    result.update(controlType=control_type, maxOfflineUsage=1)
    result["lastUsed"]["id"] = usage_id
    return result


@pytest.mark.parametrize("control_type", ["machine", "door", "nuki"])
@pytest.mark.parametrize("is_on", [True, False])
async def test_timeout_publishes_unknown_without_polling_or_retry(
    coordinator, control_type, is_on
):
    coordinator.async_set_updated_data({1: resource(control_type)})
    before = deepcopy(coordinator.data)
    switch = FabmanSwitch(coordinator, 1, control_type)
    sensor = FabmanSensor(coordinator, 1, "Synthetic", control_type, 1)
    activity = FabmanActivitySensor(coordinator, 1, "first")
    listener = Mock()
    remove = coordinator.async_add_listener(listener)
    coordinator.async_request_refresh = AsyncMock()
    try:
        with (
            patch(
                "custom_components.fabman.coordinator.COMMAND_CONFIRMATION_TIMEOUT",
                0.01,
            ),
            patch(
                "custom_components.fabman.coordinator.persistent_notification.async_create"
            ) as notify,
        ):
            coordinator.async_note_command(1, is_on)
            assert switch.assumed_state and switch.is_on is is_on
            listener.reset_mock()
            await asyncio.sleep(0.05)
        assert not switch.assumed_state
        assert switch.is_on is None
        assert activity.is_on is None and sensor.native_value is None
        assert activity.extra_state_attributes["status_reason"] == "command_timeout"
        assert sensor.extra_state_attributes["status_reason"] == "command_timeout"
        assert not coordinator.pending_commands
        assert not coordinator._command_timeout_timers
        assert coordinator.data == before
        assert coordinator.update_interval is None
        listener.assert_called_once()
        notify.assert_called_once()
        coordinator.async_request_refresh.assert_not_awaited()
    finally:
        remove()


async def test_deadline_is_thirty_seconds_and_old_snapshot_does_not_extend_it(
    coordinator,
):
    coordinator.async_set_updated_data({1: resource()})
    start = coordinator.hass.loop.time()
    coordinator.async_note_command(1, True)
    timer = coordinator._command_timeout_timers[1]
    assert COMMAND_CONFIRMATION_TIMEOUT == 30
    assert 29.9 <= timer.when() - start <= 30.1
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[resource()]),
    ):
        await coordinator.async_refresh()
    assert coordinator._command_timeout_timers[1] is timer


async def test_confirmation_before_deadline_cancels_error(coordinator):
    coordinator.async_set_updated_data({1: resource()})
    with (
        patch(
            "custom_components.fabman.coordinator.COMMAND_CONFIRMATION_TIMEOUT", 0.01
        ),
        patch(
            "custom_components.fabman.coordinator.persistent_notification.async_create"
        ) as notify,
    ):
        coordinator.async_note_command(1, True)
        timer = coordinator._command_timeout_timers[1]
        coordinator.async_set_updated_data({1: resource(usage_id=11)})
        await asyncio.sleep(0.05)
    assert timer.cancelled()
    assert not coordinator.pending_commands and not coordinator.timed_out_commands
    assert coordinator.activity(1).is_on is False
    notify.assert_not_called()


async def test_late_confirmation_recovers_but_old_grant_does_not(coordinator):
    coordinator.async_set_updated_data({1: resource()})
    with patch(
        "custom_components.fabman.coordinator.COMMAND_CONFIRMATION_TIMEOUT", 0.01
    ):
        coordinator.async_note_command(1, True)
    await asyncio.sleep(0.05)
    notifications = persistent_notification._async_get_or_create_notifications(
        coordinator.hass
    )
    assert len(notifications) == 1
    coordinator.async_set_updated_data({1: resource()})
    assert coordinator.activity(1).reason == "command_timeout"
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[resource(usage_id=11)]),
    ):
        await coordinator.async_refresh()
    assert not coordinator.timed_out_commands
    assert coordinator.activity(1).is_on is False
    assert not notifications


async def test_timeout_during_api_failure_does_not_forge_recovery(coordinator):
    coordinator.async_set_updated_data({1: resource()})
    with patch(
        "custom_components.fabman.coordinator.COMMAND_CONFIRMATION_TIMEOUT", 0.01
    ):
        coordinator.async_note_command(1, True)
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=FabmanAPIError("HTTP 503")),
    ):
        await coordinator.async_refresh()
    await asyncio.sleep(0.05)
    assert coordinator.activity(1).reason == "command_timeout"
    assert not coordinator.last_update_success
    assert not FabmanSwitch(coordinator, 1, "door").available


async def test_stale_timeout_cannot_expire_a_new_command(coordinator):
    coordinator.async_set_updated_data({1: resource()})
    coordinator.async_note_command(1, True)
    old_command = coordinator.pending_commands[1]
    old_timer = coordinator._command_timeout_timers[1]
    coordinator.async_note_command(1, False)
    current = coordinator.pending_commands[1]
    with patch(
        "custom_components.fabman.coordinator.persistent_notification.async_create"
    ) as notify:
        coordinator._command_timed_out(1, old_command)
    assert old_timer.cancelled()
    assert coordinator.pending_commands[1] is current
    assert not coordinator.timed_out_commands
    notify.assert_not_called()


async def test_unload_cancels_command_deadline_and_suppresses_late_callback(
    coordinator,
):
    coordinator.async_set_updated_data({1: resource()})
    with patch(
        "custom_components.fabman.coordinator.COMMAND_CONFIRMATION_TIMEOUT", 0.01
    ):
        coordinator.async_note_command(1, True)
    command = coordinator.pending_commands[1]
    timer = coordinator._command_timeout_timers[1]
    with patch(
        "custom_components.fabman.coordinator.persistent_notification.async_create"
    ) as notify:
        coordinator.async_cancel_pending_updates()
        coordinator._command_timed_out(1, command)
        await asyncio.sleep(0.05)
    assert timer.cancelled()
    assert not coordinator._command_timeout_timers
    assert not coordinator.pending_commands and not coordinator.timed_out_commands
    notify.assert_not_called()


@pytest.mark.parametrize("change", ["removed", "archived", "type"])
async def test_inactive_resource_clears_expired_command(coordinator, change):
    coordinator.async_set_updated_data({1: resource()})
    with patch(
        "custom_components.fabman.coordinator.COMMAND_CONFIRMATION_TIMEOUT", 0.01
    ):
        coordinator.async_note_command(1, True)
    await asyncio.sleep(0.05)
    changed = resource()
    if change == "archived":
        changed["state"] = "archived"
    elif change == "type":
        changed["controlType"] = "pos"
    coordinator.async_set_updated_data({} if change == "removed" else {1: changed})
    assert not coordinator.timed_out_commands


async def test_in_flight_read_can_confirm_after_timeout(coordinator):
    coordinator.async_set_updated_data({1: resource()})
    coordinator.async_note_command(1, True)
    command = coordinator.pending_commands[1]
    started, finish = asyncio.Event(), asyncio.Event()

    async def fetch():
        started.set()
        await finish.wait()
        granted = resource(usage_id=11)
        granted["lastUsed"]["at"] = (
            dt_util.utcnow() - timedelta(seconds=2)
        ).isoformat()
        return [granted]

    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=fetch),
    ):
        task = asyncio.create_task(coordinator.async_refresh())
        await asyncio.wait_for(started.wait(), 1)
        coordinator._command_timed_out(1, command)
        finish.set()
        await task
    assert not coordinator.timed_out_commands
    assert coordinator.activity(1).is_on is False
