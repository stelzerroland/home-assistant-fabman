"""Interpret only stable Nuki lock and battery states returned by Fabman."""

import pytest

from custom_components.fabman.nuki import (
    battery_level,
    device_identifier,
    is_unlocked,
    normalized_identifier,
)


@pytest.mark.parametrize("state", [1])
def test_nuki_locked_state_maps_to_ha_binary_sensor_off(state):
    assert is_unlocked({"serverState": 0, "state": {"state": state}}) is False


@pytest.mark.parametrize("state", [3, 5, 6])
def test_nuki_unlocked_or_unlatched_states_map_to_ha_binary_sensor_on(state):
    assert is_unlocked({"serverState": 0, "state": {"state": state}}) is True


@pytest.mark.parametrize("state", [None, 0, 2, 4, 7, "1"])
def test_unknown_or_transition_nuki_states_remain_unknown(state):
    assert is_unlocked({"serverState": 0, "state": {"state": state}}) is None


def test_nuki_offline_and_malformed_payloads_do_not_report_a_lock_state():
    assert is_unlocked({"serverState": 1, "state": {"state": 1}}) is None
    assert is_unlocked({"state": []}) is None
    assert is_unlocked(None) is None
    assert is_unlocked({"type": 2, "state": {"state": 1}}) is None


@pytest.mark.parametrize("value", [0, 1, 80, 100])
def test_nuki_battery_accepts_only_percent_values(value):
    assert battery_level({"serverState": 0, "state": {"batteryCharge": value}}) == value


@pytest.mark.parametrize("value", [-1, 101, True, 80.5, "80"])
def test_nuki_battery_rejects_invalid_values(value):
    assert battery_level({"state": {"batteryCharge": value}}) is None


def test_device_identifiers_are_normalized_safely():
    assert normalized_identifier(88) == "88"
    assert normalized_identifier("0088") == "88"
    assert device_identifier({"smartlockId": "0088", "id": 99}) == "88"
    assert device_identifier({"id": 0}) is None
