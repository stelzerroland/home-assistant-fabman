"""Regression coverage for errors, door states and removed resources."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.fabman.sensor import FabmanSensor
from custom_components.fabman.switch import FabmanSwitch


def entities(coordinator):
    resource = coordinator.data[1]
    return (
        FabmanSwitch(coordinator, 1, resource["controlType"]),
        FabmanSensor(coordinator, 1, "Test resource", resource["controlType"], 10),
    )


def session_with_status(status):
    response = Mock(status=status)
    context = AsyncMock()
    context.__aenter__.return_value = response
    return Mock(post=Mock(return_value=context))


async def test_null_last_used_is_unknown_until_never_used_semantics_are_verified(
    coordinator,
):
    switch, sensor = entities(coordinator)
    assert switch.is_on is None
    assert sensor.state is None
    assert sensor.extra_state_attributes["status_reason"] == "null_usage_unverified"
    assert sensor.extra_state_attributes["last_used_at"] == "Unknown"
    assert sensor.device_class is None
    assert sensor.state_class is None


@pytest.mark.parametrize("status", [401, 403, 500])
@pytest.mark.parametrize("action", ["async_turn_on", "async_turn_off"])
async def test_http_errors_reach_caller_without_changing_data(
    coordinator, status, action
):
    switch, _ = entities(coordinator)
    before = deepcopy(coordinator.data)
    with (
        patch(
            "custom_components.fabman.switch.async_get_clientsession",
            return_value=session_with_status(status),
        ),
        pytest.raises(HomeAssistantError, match=f"HTTP {status}"),
    ):
        await getattr(switch, action)()
    assert coordinator.data == before
    assert not coordinator._refresh_timers


@pytest.mark.parametrize("error", [aiohttp.ClientConnectionError(), TimeoutError()])
async def test_connection_errors_reach_caller(coordinator, error):
    switch, _ = entities(coordinator)
    session = Mock(post=Mock(side_effect=error))
    with (
        patch(
            "custom_components.fabman.switch.async_get_clientsession",
            return_value=session,
        ),
        pytest.raises(HomeAssistantError, match="Unable to control"),
    ):
        await switch.async_turn_on()
    assert coordinator.data[1]["lastUsed"] is None


@pytest.mark.parametrize("control_type", ["machine", "door", "nuki"])
async def test_success_reports_an_assumption_without_forging_activity(
    coordinator, control_type
):
    coordinator.data[1]["controlType"] = control_type
    switch, sensor = entities(coordinator)
    session = session_with_status(201)
    before = deepcopy(coordinator.data)
    listener = Mock()
    remove_listener = coordinator.async_add_listener(listener)
    try:
        with patch(
            "custom_components.fabman.switch.async_get_clientsession",
            return_value=session,
        ):
            await asyncio.wait_for(switch.async_turn_on(), timeout=0.5)
            assert switch.is_on
            assert switch.assumed_state
            assert switch.extra_state_attributes["state_source"] == "command_assumption"
            assert sensor.state is None
            assert (
                sensor.extra_state_attributes["status_reason"] == "command_unconfirmed"
            )
            assert coordinator.data == before
            listener.assert_called()
            assert coordinator._refresh_timers
            await asyncio.wait_for(switch.async_turn_off(), timeout=0.5)
            assert not switch.is_on
            assert switch.assumed_state
            assert sensor.state is None
            assert coordinator.data == before
        assert session.post.call_count == 2
    finally:
        remove_listener()


async def test_missing_resource_becomes_unavailable_and_retains_identity(coordinator):
    switch, sensor = entities(coordinator)
    identities = switch.device_info, sensor.device_info
    coordinator.async_set_updated_data({})
    assert not switch.available
    assert not sensor.available
    assert (switch.device_info, sensor.device_info) == identities
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await switch.async_turn_on()
    coordinator.async_note_command(1, True)
    assert coordinator.data == {}


async def test_coordinator_failure_marks_entities_unavailable(coordinator):
    switch, sensor = entities(coordinator)
    coordinator.last_update_success = False
    assert not switch.available
    assert not sensor.available


async def test_expired_door_release_is_off_without_server_off_event(coordinator):
    coordinator.data[1].update(
        controlType="door",
        lastUsed={"at": (dt_util.utcnow() - timedelta(seconds=20)).isoformat()},
    )
    switch, sensor = entities(coordinator)
    assert switch.is_on is False
    assert sensor.state == "off"


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-13-40T00:00:00Z"])
async def test_invalid_door_timestamp_does_not_crash(coordinator, timestamp):
    coordinator.data[1].update(controlType="door", lastUsed={"at": timestamp})
    switch, sensor = entities(coordinator)
    assert switch.is_on is None
    assert sensor.state is None
