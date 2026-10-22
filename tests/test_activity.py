"""Semantic boundaries: unknown must never silently become off."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.fabman.activity import evaluate_activity

from .factories import machine

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("active", [True, False])
def test_explicit_consistent_machine_sessions(active):
    resource = machine(active=active)
    before = deepcopy(resource)
    assert evaluate_activity(resource, now=NOW).is_on is active
    assert resource == before


@pytest.mark.parametrize(
    ("usage", "reason"),
    [
        (None, "null_usage_unverified"),
        ({}, "invalid_usage"),
        ([], "invalid_usage"),
        ("bad", "invalid_usage"),
        (True, "invalid_usage"),
        ({"at": "2020-01-01T10:00:00Z"}, "stop_type_missing"),
        ({"stopType": {}}, "invalid_stop_type"),
        ({"stopType": "new_value"}, "unknown_stop_type"),
    ],
)
def test_incomplete_usage_is_unknown(usage, reason):
    resource = machine()
    resource["lastUsed"] = usage
    activity = evaluate_activity(resource, now=NOW)
    assert activity.is_on is None
    assert activity.reason == reason


def test_missing_key_is_distinct_from_null():
    resource = machine()
    resource.pop("lastUsed")
    assert evaluate_activity(resource).reason == "usage_missing"


@pytest.mark.parametrize("stop_type", ["offline", "takeover", "race"])
def test_ambiguous_stops_do_not_claim_machine_inactivity(stop_type):
    resource = machine(active=False)
    resource["lastUsed"]["stopType"] = stop_type
    assert evaluate_activity(resource, now=NOW).is_on is None


@pytest.mark.parametrize("stop_type", ["normal", "automatic", "filter", "permission"])
def test_known_stops_require_a_valid_end_timestamp(stop_type):
    resource = machine(active=False)
    resource["lastUsed"]["stopType"] = stop_type
    assert evaluate_activity(resource, now=NOW).is_on is False
    resource["lastUsed"].pop("stoppedAt")
    assert evaluate_activity(resource, now=NOW).is_on is None


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        123,
        "invalid",
        "2020-01-01T10:00:00",
        "2026-13-40T00:00:00Z",
        (NOW + timedelta(seconds=1)).isoformat(),
    ],
)
def test_invalid_naive_or_future_timestamp_is_unknown(timestamp):
    resource = machine()
    resource["lastUsed"]["at"] = timestamp
    assert evaluate_activity(resource, now=NOW).is_on is None


def test_active_usage_with_end_is_unknown():
    resource = machine()
    resource["lastUsed"]["stoppedAt"] = "2020-01-01T11:00:00Z"
    assert evaluate_activity(resource, now=NOW).is_on is None


@pytest.mark.parametrize("stop_type", ["normal", "automatic", "filter", "permission"])
@pytest.mark.parametrize(
    "reported_at",
    [
        "2020-01-01T10:00:00Z",  # Before stop, supported by older synthetic examples.
        "2020-01-01T11:00:00.002Z",  # Log update a few milliseconds after stop.
        "2020-01-02T18:45:00Z",  # A later log update must not look like a new start.
    ],
)
def test_stopped_usage_does_not_treat_last_used_at_as_start(stop_type, reported_at):
    resource = machine(active=False)
    resource["lastUsed"].update(at=reported_at, stopType=stop_type)
    result = evaluate_activity(resource, now=NOW)
    assert result.is_on is False
    assert result.reason == "usage_stopped"


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        123,
        "invalid",
        "2020-01-01T11:00:00",
        (NOW + timedelta(seconds=1)).isoformat(),
    ],
)
def test_stopped_usage_still_requires_a_valid_aware_nonfuture_stop(timestamp):
    resource = machine(active=False)
    resource["lastUsed"]["stoppedAt"] = timestamp
    result = evaluate_activity(resource, now=NOW)
    assert result.is_on is None
    assert result.reason == "invalid_stop_timestamp"


def test_timezone_offsets_are_compared_as_instants():
    resource = machine(active=False)
    resource["lastUsed"].update(
        at="2020-01-01T12:00:00+02:00", stoppedAt="2020-01-01T10:30:00Z"
    )
    assert evaluate_activity(resource, now=NOW).is_on is False


@pytest.mark.parametrize(
    "duration", [None, 0, -1, True, "invalid", float("inf"), float("nan"), 1e300]
)
def test_invalid_door_duration_is_unknown(duration):
    resource = machine(active=False)
    resource.update(controlType="door", maxOfflineUsage=duration)
    assert evaluate_activity(resource, now=NOW).is_on is None
    assert evaluate_activity(resource, now=NOW).reason == "invalid_door_release_window"


@pytest.mark.parametrize("stop_type", [None, "normal", "automatic"])
@pytest.mark.parametrize(
    "elapsed, expected", [(0, True), (9.999, True), (10, False), (11, False)]
)
def test_door_release_uses_grant_time_even_if_session_already_ended(
    stop_type, elapsed, expected
):
    resource = machine(active=False)
    resource.update(controlType="door", maxOfflineUsage=10)
    resource["lastUsed"].update(at=NOW.isoformat(), stopType=stop_type)
    result = evaluate_activity(resource, now=NOW + timedelta(seconds=elapsed))
    assert result.is_on is expected
    assert result.source == "door_release_timer"
    assert result.reason == (
        "door_release_active" if expected else "door_release_expired"
    )


@pytest.mark.parametrize(
    "timestamp",
    [None, "bad", "2026-10-20T12:00:00", (NOW + timedelta(seconds=1)).isoformat()],
)
def test_invalid_door_grant_time_is_unknown(timestamp):
    resource = machine()
    resource.update(controlType="door", maxOfflineUsage=10, lastUsed={"at": timestamp})
    assert evaluate_activity(resource, now=NOW).is_on is None


@pytest.mark.parametrize("elapsed, expected", [(0, True), (9.999, True), (10, False)])
def test_nuki_access_activity_uses_the_fabman_release_window(elapsed, expected):
    resource = machine()
    resource.update(controlType="nuki", maxOfflineUsage=10)
    resource["lastUsed"].update(at=NOW.isoformat(), stopType="automatic")

    result = evaluate_activity(resource, now=NOW + timedelta(seconds=elapsed))

    assert result.is_on is expected
    assert result.source == "nuki_access_timer"
    assert result.reason == (
        "nuki_access_active" if expected else "nuki_access_expired"
    )


def test_long_running_machine_does_not_expire_arbitrarily():
    assert evaluate_activity(machine(), now=NOW).is_on is True


@pytest.mark.parametrize(
    "embedded", [None, [], {"bridge": None}, {"bridge": []}, {"bridge": {}}]
)
def test_missing_or_invalid_bridge_data_is_unknown(embedded):
    resource = machine()
    resource["_embedded"] = embedded
    assert evaluate_activity(resource, now=NOW).is_on is None
