"""Native binary activity, legacy identity and passive platform setup."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from custom_components.fabman import PLATFORMS
from custom_components.fabman.binary_sensor import (
    FabmanActivitySensor,
    FabmanConnectivitySensor,
    async_setup_entry,
)
from custom_components.fabman.sensor import FabmanSensor
from custom_components.fabman.switch import FabmanSwitch

from .factories import machine


@pytest.mark.parametrize("active", [True, False])
async def test_binary_sensor_has_native_states_and_shares_legacy_device(
    coordinator, active
):
    coordinator.async_set_updated_data({1: machine(active=active)})
    sensor = FabmanActivitySensor(coordinator, 1, "first")
    legacy = FabmanSensor(coordinator, 1, "Machine", "machine", 10)
    switch = FabmanSwitch(coordinator, 1, "machine")
    assert "binary_sensor" in PLATFORMS
    assert isinstance(sensor, BinarySensorEntity)
    assert sensor.device_class is BinarySensorDeviceClass.RUNNING
    assert sensor.state == ("on" if active else "off")
    assert legacy.state == sensor.state
    assert switch.is_on is active
    assert sensor.device_info == legacy.device_info == switch.device_info
    assert legacy.unique_id == "fabman_sensor_1"
    assert switch.unique_id == "fabman_switch_1"


async def test_same_resource_in_two_connections_has_distinct_new_unique_ids(
    coordinator,
):
    first = FabmanActivitySensor(coordinator, 1, "first")
    second = FabmanActivitySensor(coordinator, 1, "second")
    assert first.unique_id != second.unique_id
    assert first.device_info == second.device_info


async def test_unknown_and_unavailable_are_distinct(coordinator):
    sensor = FabmanActivitySensor(coordinator, 1, "first")
    assert sensor.available
    assert sensor.is_on is None
    assert sensor.state is None
    assert sensor.extra_state_attributes["status_reason"] == "null_usage_unverified"
    coordinator.last_update_success = False
    assert not sensor.available
    coordinator.last_update_success = True
    coordinator.async_set_updated_data({})
    assert not sensor.available


async def test_door_never_looks_like_a_physical_contact(coordinator):
    coordinator.data[1]["controlType"] = "door"
    sensor = FabmanActivitySensor(coordinator, 1, "first")
    assert sensor.device_class is None
    assert sensor.state is None
    assert sensor.extra_state_attributes["status_reason"] == "null_usage_unverified"


async def test_command_assumption_does_not_become_activity(coordinator):
    coordinator.async_set_updated_data({1: machine(active=False)})
    sensor = FabmanActivitySensor(coordinator, 1, "first")
    switch = FabmanSwitch(coordinator, 1, "machine")
    coordinator.async_note_command(1, True)
    assert switch.is_on is True
    assert switch.assumed_state
    assert sensor.is_on is None
    assert sensor.extra_state_attributes["status_reason"] == "command_unconfirmed"


async def test_platform_setup_is_passive_and_filters_unsupported_resources(
    coordinator, hass
):
    supported = machine()
    door = {**machine(2), "controlType": "door"}
    no_bridge = {**machine(3), "_embedded": {"bridge": None}}
    unsupported = {**machine(4), "controlType": "unsupported"}
    malformed = {**machine(5), "_embedded": ["invalid"]}
    coordinator.async_set_updated_data(
        {r["id"]: r for r in [supported, door, no_bridge, unsupported, malformed]}
    )
    entities = []
    coordinator._session.post = Mock(
        side_effect=AssertionError("Status setup must not send POST")
    )
    await async_setup_entry(
        hass,
        SimpleNamespace(entry_id="first", async_on_unload=Mock()),
        lambda added: entities.extend(added),
    )
    assert len(entities) == 4
    assert sum(isinstance(entity, FabmanConnectivitySensor) for entity in entities) == 2
    assert {entity.extra_state_attributes["resource_id"] for entity in entities} == {
        1,
        2,
    }
    coordinator._session.post.assert_not_called()
