"""Connectivity is an explicit server flag, independent of activity and API health."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.fabman.activity import evaluate_activity
from custom_components.fabman.binary_sensor import (
    FabmanActivitySensor,
    FabmanConnectivitySensor,
)
from custom_components.fabman.connectivity import bridge_is_connected
from custom_components.fabman.sensor import FabmanSensor
from custom_components.fabman.switch import FabmanSwitch

from .factories import machine


@pytest.mark.parametrize("offline, expected", [(False, True), (True, False)])
async def test_connectivity_has_native_state_and_existing_device(
    coordinator, offline, expected
):
    resource = machine()
    resource["_embedded"]["bridge"]["offline"] = offline
    coordinator.async_set_updated_data({1: resource})
    sensor = FabmanConnectivitySensor(coordinator, 1, "first")
    activity = FabmanActivitySensor(coordinator, 1, "first")
    assert sensor.name == "Connectivity"
    assert sensor.device_class is BinarySensorDeviceClass.CONNECTIVITY
    assert sensor.is_on is expected
    assert sensor.state == ("on" if expected else "off")
    assert sensor.device_info == activity.device_info
    assert sensor.unique_id == "fabman_connectivity_first_1"
    assert (
        sensor.unique_id != FabmanConnectivitySensor(coordinator, 1, "second").unique_id
    )


@pytest.mark.parametrize("offline", [None, "false", "true", 0, 1, [], {}])
async def test_missing_or_malformed_flag_does_not_claim_online_or_off(
    coordinator, offline
):
    resource = machine(active=False)
    resource["_embedded"]["bridge"]["offline"] = offline
    coordinator.async_set_updated_data({1: resource})
    sensor = FabmanConnectivitySensor(coordinator, 1, "first")
    assert bridge_is_connected(resource) is None
    assert sensor.available
    assert sensor.is_on is None
    assert evaluate_activity(resource).is_on is None
    assert (
        sensor.extra_state_attributes["status_reason"] == "bridge_connectivity_unknown"
    )


def test_absent_flag_is_unknown_even_with_recent_timestamp_or_in_use():
    resource = machine()
    resource["_embedded"]["bridge"] = {
        "updatedAt": "2026-10-20T12:00:00Z",
        "inUse": True,
    }
    assert bridge_is_connected(resource) is None
    assert evaluate_activity(resource).reason == "bridge_connectivity_unknown"


@pytest.mark.parametrize(
    "resource",
    [None, {}, {"_embedded": None}, {"_embedded": []}, {"_embedded": {"bridge": []}}],
)
def test_malformed_resource_connectivity_is_unknown(resource):
    assert bridge_is_connected(resource) is None


@pytest.mark.parametrize("control_type", ["machine", "door"])
@pytest.mark.parametrize("active", [True, False])
async def test_offline_bridge_masks_active_and_ended_usage(
    coordinator, control_type, active
):
    resource = machine(active=active)
    resource.update(controlType=control_type, maxOfflineUsage=10)
    resource["_embedded"]["bridge"]["offline"] = True
    coordinator.async_set_updated_data({1: resource})
    activity = FabmanActivitySensor(coordinator, 1, "first")
    status = FabmanSensor(coordinator, 1, "Synthetic", control_type, 10)
    switch = FabmanSwitch(coordinator, 1, control_type)
    assert activity.available
    assert activity.is_on is None
    assert status.native_value is None
    assert switch.is_on is None
    assert activity.extra_state_attributes["status_reason"] == "bridge_offline"
    assert activity.extra_state_attributes["status_source"] == "fabman_bridge"
    assert not coordinator._door_timers


async def test_api_failure_and_resource_removal_make_connectivity_unavailable(
    coordinator,
):
    coordinator.async_set_updated_data({1: machine()})
    sensor = FabmanConnectivitySensor(coordinator, 1, "first")
    coordinator.last_update_success = False
    assert not sensor.available
    coordinator.last_update_success = True
    coordinator.async_set_updated_data({})
    assert not sensor.available


async def test_commands_do_not_change_connectivity_and_offline_read_does_not_confirm(
    coordinator,
):
    resource = machine(active=False)
    coordinator.async_set_updated_data({1: resource})
    sensor = FabmanConnectivitySensor(coordinator, 1, "first")
    coordinator.async_note_command(1, False)
    assert sensor.is_on is True
    offline = deepcopy(resource)
    offline["_embedded"]["bridge"]["offline"] = True
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[offline]),
    ):
        await coordinator.async_refresh()
    assert sensor.is_on is False
    assert 1 in coordinator.pending_commands
    assert coordinator.activity(1).is_on is None


async def test_losing_connectivity_cancels_an_active_door_timer(coordinator):
    from homeassistant.util import dt as dt_util

    resource = machine()
    resource.update(
        controlType="door",
        maxOfflineUsage=60,
        lastUsed={"at": dt_util.utcnow().isoformat()},
    )
    coordinator.async_set_updated_data({1: resource})
    handle = coordinator._door_timers[1]
    offline = deepcopy(resource)
    offline["_embedded"]["bridge"]["offline"] = True
    coordinator.async_set_updated_data({1: offline})
    assert handle.cancelled()
    assert not coordinator._door_timers
    coordinator._door_expired(1)
    assert coordinator.activity(1).is_on is None
