"""A short confirmed release can finish before command reconciliation reads it."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.fabman.binary_sensor import FabmanActivitySensor
from custom_components.fabman.sensor import FabmanSensor
from custom_components.fabman.switch import FabmanSwitch

from .factories import machine


def door(*, usage_id=10, seconds_ago=60, usage_type="allowed"):
    resource = machine(active=False)
    timestamp = (dt_util.utcnow() - timedelta(seconds=seconds_ago)).isoformat()
    resource.update(
        controlType="door",
        maxOfflineUsage=3,
        lastUsed={
            "id": usage_id,
            "at": timestamp,
            "stoppedAt": timestamp,
            "stopType": "normal",
            "type": usage_type,
        },
    )
    return resource


async def test_expired_new_release_confirms_open_and_clears_assumed_on(coordinator):
    coordinator.async_set_updated_data({1: door()})
    switch = FabmanSwitch(coordinator, 1, "door")
    binary = FabmanActivitySensor(coordinator, 1, "first")
    sensor = FabmanSensor(coordinator, 1, "Synthetic door", "door", 3)
    coordinator.async_note_command(1, True)
    assert switch.is_on is True and switch.assumed_state
    assert binary.is_on is None
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[door(usage_id=11, seconds_ago=5)]),
    ):
        await coordinator.async_refresh()
    assert not switch.assumed_state
    assert switch.is_on is False
    assert binary.is_on is False
    assert sensor.native_value == "off"
    assert not coordinator._door_timers


@pytest.mark.parametrize(
    "case",
    [
        "same_usage",
        "offline",
        "denied",
        "missing_id",
        "invalid_time",
        "invalid_duration",
    ],
)
async def test_no_false_confirmation_from_old_or_unreliable_release(coordinator, case):
    coordinator.async_set_updated_data({1: door()})
    coordinator.async_note_command(1, True)
    resource = door(usage_id=11, seconds_ago=5)
    if case == "same_usage":
        resource["lastUsed"]["id"] = 10
    elif case == "offline":
        resource["_embedded"]["bridge"]["offline"] = True
    elif case == "denied":
        resource["lastUsed"]["type"] = "denied"
    elif case == "missing_id":
        resource["lastUsed"].pop("id")
    elif case == "invalid_time":
        resource["lastUsed"]["at"] = "bad"
    else:
        resource["maxOfflineUsage"] = 0
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[resource]),
    ):
        await coordinator.async_refresh()
    assert 1 in coordinator.pending_commands
    assert coordinator.activity(1).is_on is None


async def test_confirmed_active_release_expires_without_off_event(coordinator):
    coordinator.async_set_updated_data({1: door()})
    switch = FabmanSwitch(coordinator, 1, "door")
    coordinator.async_note_command(1, True)
    resource = door(usage_id=11, seconds_ago=0)
    resource["maxOfflineUsage"] = 0.05
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[resource]),
    ):
        await coordinator.async_refresh()
    assert switch.is_on is True
    assert not switch.assumed_state
    await asyncio.sleep(0.1)
    assert switch.is_on is False
    assert coordinator.activity(1).is_on is False


async def test_grant_arriving_during_post_uses_pre_request_baseline(coordinator):
    coordinator.async_set_updated_data({1: door()})
    switched = FabmanSwitch(coordinator, 1, "door")
    resource = door(usage_id=11, seconds_ago=5)

    async def accepted():
        coordinator.async_set_updated_data({1: resource})
        return Mock(status=201)

    context = AsyncMock()
    context.__aenter__.side_effect = accepted
    session = Mock(post=Mock(return_value=context))
    with patch(
        "custom_components.fabman.switch.async_get_clientsession", return_value=session
    ):
        await switched.async_turn_on()
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[resource]),
    ):
        await coordinator.async_refresh()
    assert not switched.assumed_state
    assert switched.is_on is False
