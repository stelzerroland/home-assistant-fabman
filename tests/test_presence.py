"""Attendance sessions exercise catch-up, reconciliation and scope isolation."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.fabman.api import FabmanAPIError, FabmanNotFoundError
from custom_components.fabman.presence import PresenceTracker, parse_session

from .factories import machine

BASE = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
SCOPE = (42, 5)


def terminal(resource_id=1370, *, space=5):
    return {**machine(resource_id), "controlType": "checkIn", "space": space}


def attendance(log_id=10, *, member=6, resource=1370, start=1, end=None):
    return {
        "id": log_id,
        "account": 42,
        "type": "checkIn",
        "resource": resource,
        "member": {
            "id": member,
            "account": 42,
            "firstName": "Synthetic",
            "lastName": f"Member {member}",
            "emailAddress": "private@example.test",
            "notes": "private-notes",
        },
        "createdAt": (BASE + timedelta(seconds=start)).isoformat(),
        "stoppedAt": (BASE + timedelta(seconds=end)).isoformat()
        if end is not None
        else None,
        "stopType": "normal" if end is not None else None,
    }


class AttendanceAPI:
    def __init__(self):
        self.active = []
        self.recent = []
        self.get_space = AsyncMock(
            return_value={"id": 5, "account": 42, "name": "Synthetic space"}
        )
        self.get_check_in_log = AsyncMock()
        self.calls = []

    async def get_check_in_logs(self, account_id, space_id, **kwargs):
        self.calls.append((account_id, space_id, kwargs))
        value = self.recent if kwargs.get("status") == "all" else self.active
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)


async def refresh(tracker, api, seconds=0, resources=None):
    states, events, failures = await tracker.async_prepare(
        api,
        resources if resources is not None else {1370: terminal()},
        BASE + timedelta(seconds=seconds),
    )
    tracker.spaces = states
    return events, failures


async def test_first_sync_rebuilds_people_without_historical_events():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-86400), attendance(11, member=7, start=-5)]
    events, failures = await refresh(tracker, api)
    assert not events and not failures
    state = tracker.spaces[SCOPE]
    assert state.available and len(state.members) == 2
    assert state.name == "Synthetic space"
    assert all("status" not in kwargs for _, _, kwargs in api.calls)
    assert "private@example.test" not in repr(state)
    assert "private-notes" not in repr(state)


async def test_complete_short_visit_between_polls_emits_both_events_once_in_order():
    tracker, api = PresenceTracker(), AttendanceAPI()
    await refresh(tracker, api)
    api.recent = [attendance(start=2, end=10)]
    events, failures = await refresh(tracker, api, 30)
    assert not failures
    assert [event["event_type"] for event in events] == ["checked_in", "checked_out"]
    assert [event["member_id"] for event in events] == [6, 6]
    assert events[0]["space_id"] == 5 and events[0]["resource_id"] == 1370
    assert events[0]["member_name"] == "Synthetic Member 6"
    assert tracker.spaces[SCOPE].members == []
    assert "private@example.test" not in repr(events)
    assert (await refresh(tracker, api, 60))[0] == []


async def test_long_open_session_is_re_read_by_id_when_it_closes():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-86400)]
    await refresh(tracker, api)
    api.active = []
    api.get_check_in_log.return_value = attendance(start=-86400, end=15)
    events, failures = await refresh(tracker, api, 30)
    assert not failures
    api.get_check_in_log.assert_awaited_once_with(10)
    assert [event["event_type"] for event in events] == ["checked_out"]
    assert tracker.spaces[SCOPE].members == []


async def test_baseline_session_does_not_generate_a_late_duplicate_check_in():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=1)]  # Created while the first request was in flight.
    await refresh(tracker, api)
    api.active = []
    api.recent = [attendance(start=1, end=10)]
    api.get_check_in_log.return_value = attendance(start=1, end=10)
    assert [e["event_type"] for e in (await refresh(tracker, api, 30))[0]] == [
        "checked_out"
    ]
    assert (await refresh(tracker, api, 60))[0] == []


async def test_multiple_terminals_count_each_member_once_until_last_session_closes():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-100), attendance(11, resource=1371, start=-50)]
    resources = {1370: terminal(), 1371: terminal(1371)}
    await refresh(tracker, api, resources=resources)
    state = tracker.spaces[SCOPE]
    assert len(state.members) == 1 and len(state.sessions) == 2
    assert state.members[0]["resource_ids"] == [1370, 1371]
    api.active.pop(0)
    api.get_check_in_log.return_value = attendance(start=-100, end=10)
    await refresh(tracker, api, 30, resources)
    assert len(tracker.spaces[SCOPE].members) == 1


async def test_failed_read_preserves_list_and_watermark_then_catches_up():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-100)]
    await refresh(tracker, api)
    api.active = FabmanAPIError("HTTP 503")
    events, failures = await refresh(tracker, api, 30)
    assert failures and not events
    state = tracker.spaces[SCOPE]
    assert not state.available and len(state.members) == 1
    assert state.cursor == BASE
    api.active = []
    api.recent = [attendance(11, member=7, start=20, end=25)]
    api.get_check_in_log.return_value = attendance(start=-100, end=15)
    events, failures = await refresh(tracker, api, 90)
    assert not failures and tracker.spaces[SCOPE].available
    assert [event["event_type"] for event in events] == [
        "checked_out",
        "checked_in",
        "checked_out",
    ]


async def test_read_race_is_unavailable_and_does_not_fabricate_checkout():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-100)]
    await refresh(tracker, api)
    api.active = []
    api.get_check_in_log.return_value = attendance(start=-100)
    events, failures = await refresh(tracker, api, 30)
    assert not events and failures and not tracker.spaces[SCOPE].available
    assert len(tracker.spaces[SCOPE].members) == 1


async def test_offline_terminal_does_not_check_people_out():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-100)]
    resource = terminal()
    resource["_embedded"]["bridge"]["offline"] = True
    await refresh(tracker, api, resources={1370: resource})
    assert tracker.spaces[SCOPE].available and len(tracker.spaces[SCOPE].members) == 1


async def test_removed_terminal_makes_space_unavailable_and_reactivation_rebaselines():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-100)]
    await refresh(tracker, api)
    await refresh(tracker, api, 30, resources={})
    assert not tracker.spaces[SCOPE].active and not tracker.spaces[SCOPE].available
    assert (await refresh(tracker, api, 60))[0] == []
    assert tracker.spaces[SCOPE].active


async def test_space_failure_is_isolated_from_other_spaces():
    tracker, api = PresenceTracker(), AttendanceAPI()

    async def scoped_logs(account_id, space_id, **kwargs):
        if space_id == 5:
            raise FabmanAPIError("denied")
        return [attendance(start=-100, resource=1371)]

    api.get_check_in_logs = scoped_logs
    await refresh(
        tracker, api, resources={1370: terminal(), 1371: terminal(1371, space=6)}
    )
    assert not tracker.spaces[SCOPE].available
    assert tracker.spaces[(42, 6)].available


async def test_missing_label_does_not_disable_attendance():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.get_space.side_effect = FabmanAPIError("HTTP 403")
    await refresh(tracker, api)
    assert tracker.spaces[SCOPE].available and tracker.spaces[SCOPE].name == "Space 5"


async def test_prepare_does_not_mutate_tracker_before_coordinator_acceptance():
    tracker, api = PresenceTracker(), AttendanceAPI()
    states, _, _ = await tracker.async_prepare(api, {1370: terminal()}, BASE)
    assert SCOPE in states and tracker.spaces == {}


async def test_restart_uses_current_snapshot_without_replaying_downtime():
    tracker, api = PresenceTracker(), AttendanceAPI()
    await refresh(tracker, api)
    api.recent = [attendance(start=2, end=10)]
    restarted = PresenceTracker()
    events, failures = await refresh(restarted, api, 60)
    assert not failures and not events and restarted.spaces[SCOPE].members == []


async def test_historical_admin_correction_updates_list_without_old_live_events():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-86400)]
    await refresh(tracker, api)
    api.active = []
    api.get_check_in_log.return_value = attendance(start=-86400, end=-100)
    assert (await refresh(tracker, api, 30))[0] == []
    assert tracker.spaces[SCOPE].members == []


@pytest.mark.parametrize(
    "changes",
    [
        {"member": None},
        {"member": True},
        {"account": 99},
        {"id": True},
        {"createdAt": "2026-10-22T08:00:00"},
        {"stoppedAt": "invalid"},
        {"stopType": "normal"},
        {"stoppedAt": (BASE - timedelta(days=1)).isoformat()},
        {"type": "allowed"},
    ],
)
def test_malformed_attendance_fails_instead_of_reporting_an_incomplete_roster(changes):
    with pytest.raises(FabmanAPIError):
        parse_session({**attendance(), **changes}, 42)


async def test_duplicate_pages_fail_instead_of_double_counting():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(), attendance()]
    assert (await refresh(tracker, api))[1]
    assert not tracker.spaces[SCOPE].available


async def test_removed_session_is_reconciled_without_a_fabricated_checkout():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(start=-100)]
    await refresh(tracker, api)
    api.active = []
    api.get_check_in_log.side_effect = FabmanNotFoundError("removed")
    events, failures = await refresh(tracker, api, 30)
    assert not failures and not events
    assert tracker.spaces[SCOPE].available and tracker.spaces[SCOPE].members == []


async def test_known_resource_in_another_space_cannot_pollute_the_roster():
    tracker, api = PresenceTracker(), AttendanceAPI()
    api.active = [attendance(resource=1371)]
    await refresh(
        tracker,
        api,
        resources={
            1370: terminal(),
            1371: {
                **machine(1371),
                "space": 6,
            },
        },
    )
    assert not tracker.spaces[SCOPE].available


def test_event_listeners_stop_on_removal_and_unload():
    tracker = PresenceTracker()
    events = []
    event = {"account_id": 42, "space_id": 5, "event_type": "checked_in"}
    remove = tracker.add_listener(SCOPE, events.append)
    tracker.dispatch(event)
    remove()
    tracker.dispatch(event)
    assert events == [event]
    tracker.add_listener(SCOPE, events.append)
    tracker.close()
    tracker.dispatch(event)
    assert events == [event] and not tracker._listeners


def test_unresolved_member_uses_id_label_and_no_extra_member_data():
    session = parse_session({**attendance(), "member": 6}, 42)
    assert session.member_id == 6 and session.member_name == "Member 6"
