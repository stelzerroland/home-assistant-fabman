"""Door expiry and delayed refresh lifecycle tests."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.util import dt as dt_util

from custom_components.fabman.const import DEFAULT_API_URL, DEFAULT_POLL_INTERVAL
from custom_components.fabman.coordinator import FabmanDataUpdateCoordinator


async def test_default_config_keeps_polling_enabled(hass):
    with patch("custom_components.fabman.coordinator.async_get_clientsession"):
        coordinator = FabmanDataUpdateCoordinator(hass, {"api_token": "test"})
    assert coordinator.api_url == DEFAULT_API_URL
    assert coordinator.update_interval.total_seconds() == DEFAULT_POLL_INTERVAL
    coordinator.async_cancel_pending_updates()
    await coordinator.async_shutdown()


async def test_door_timer_publishes_off_without_polling_or_off_event(coordinator):
    coordinator.data[1].update(
        controlType="door",
        maxOfflineUsage=0.02,
        lastUsed={"at": dt_util.utcnow().isoformat()},
    )
    listener = Mock()
    remove_listener = coordinator.async_add_listener(listener)
    coordinator.async_request_refresh = AsyncMock()
    try:
        coordinator.async_set_updated_data(coordinator.data)
        assert coordinator.activity(1).is_on is True
        listener.reset_mock()
        await asyncio.sleep(0.05)
        listener.assert_called_once()
        coordinator.async_request_refresh.assert_not_awaited()
        assert coordinator.activity(1).is_on is False
        assert not coordinator._door_timers
    finally:
        remove_listener()


async def test_cancel_pending_updates_prevents_late_refresh(coordinator):
    coordinator.data[1].update(
        controlType="door",
        maxOfflineUsage=0.02,
        lastUsed={"at": dt_util.utcnow().isoformat()},
    )
    coordinator.async_set_updated_data(coordinator.data)
    coordinator.async_note_command(1, True)
    coordinator.async_schedule_refresh(1, delay=0.02)
    handles = [
        *coordinator._door_timers.values(),
        *coordinator._refresh_timers.values(),
    ]
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_cancel_pending_updates()
    assert all(handle.cancelled() for handle in handles)
    await asyncio.sleep(0.05)
    coordinator.async_request_refresh.assert_not_awaited()
    assert not coordinator._door_timers
    assert not coordinator._refresh_timers


async def test_refresh_timer_replaced_for_repeated_commands(coordinator):
    coordinator.async_schedule_refresh(1)
    first = coordinator._refresh_timers[1]
    coordinator.async_schedule_refresh(1)
    assert first.cancelled()
    assert len(coordinator._refresh_timers) == 1


async def test_api_refresh_schedules_door_timeout(coordinator):
    resource = {
        **coordinator.data[1],
        "controlType": "door",
        "lastUsed": {"at": dt_util.utcnow().isoformat()},
    }
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[resource]),
    ):
        await coordinator.async_refresh()
    assert 1 in coordinator._door_timers
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[]),
    ):
        await coordinator.async_refresh()
    assert not coordinator._door_timers
    assert coordinator.data == {}


async def test_poll_does_not_extend_release_but_new_grant_replaces_timer(coordinator):
    now = dt_util.utcnow()
    resource = deepcopy(coordinator.data[1])
    resource.update(
        controlType="door", maxOfflineUsage=10, lastUsed={"at": now.isoformat()}
    )
    coordinator.async_set_updated_data({1: resource})
    original = coordinator._door_timers[1]
    deadline = original.when()
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[deepcopy(resource)]),
    ):
        await coordinator.async_refresh()
    repeated = coordinator._door_timers[1]
    assert original.cancelled()
    assert abs(repeated.when() - deadline) < 0.05

    # A genuinely later grant gets its own full release window.
    resource["lastUsed"]["at"] = (now + timedelta(seconds=2)).isoformat()
    with patch(
        "custom_components.fabman.activity.dt_util.utcnow",
        return_value=now + timedelta(seconds=2),
    ):
        coordinator.async_set_updated_data({1: resource})
        assert coordinator.activity(1).is_on is True
    assert repeated.cancelled()
    # Timer delays use the same mocked clock as the deadline parser.
    assert len(coordinator._door_timers) == 1


async def test_old_door_grant_does_not_confirm_new_open_command(coordinator):
    resource = deepcopy(coordinator.data[1])
    now = dt_util.utcnow()
    resource.update(
        controlType="door",
        maxOfflineUsage=10,
        lastUsed={"at": (now - timedelta(seconds=1)).isoformat()},
    )
    coordinator.async_set_updated_data({1: resource})
    coordinator.async_note_command(1, True)
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[deepcopy(resource)]),
    ):
        await coordinator.async_refresh()
    assert coordinator.activity(1).is_on is None
    assert 1 in coordinator.pending_commands
    resource["lastUsed"]["at"] = now.isoformat()
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[resource]),
    ):
        await coordinator.async_refresh()
    assert coordinator.activity(1).is_on is True
    assert 1 not in coordinator.pending_commands


async def test_door_expiry_does_not_forge_recovery_from_api_error(coordinator):
    resource = deepcopy(coordinator.data[1])
    resource.update(
        controlType="door",
        maxOfflineUsage=10,
        lastUsed={"at": dt_util.utcnow().isoformat()},
    )
    coordinator.async_set_updated_data({1: resource})
    coordinator.last_update_success = False
    coordinator._door_expired(1)
    assert not coordinator.last_update_success


async def test_pos_log_updates_emit_only_new_allowed_nonpersonal_events(coordinator):
    now = dt_util.utcnow()
    resource = {**coordinator.data[1], "controlType": "pos"}
    coordinator._pos_cursors = {"1": now - timedelta(seconds=10)}
    coordinator._pos_seen_ids = {"1": {11}}
    logs = [
        {
            "id": 10,
            "resource": 1,
            "account": 42,
            "type": "allowed",
            "createdAt": (now - timedelta(seconds=3)).isoformat(),
            "stoppedAt": None,
            "stopType": None,
            "member": {"emailAddress": "private@example.com"},
        },
        {
            "id": 11,
            "resource": 1,
            "account": 42,
            "type": "allowed",
            "createdAt": (now - timedelta(seconds=2)).isoformat(),
        },
        {
            "id": 12,
            "resource": 1,
            "account": 42,
            "type": "denied",
            "createdAt": (now - timedelta(seconds=1)).isoformat(),
        },
        {
            "id": 13,
            "resource": 1,
            "account": 42,
            "type": "allowed",
            "createdAt": {"invalid": "timestamp"},
        },
    ]
    api = SimpleNamespace(get_resource_logs=AsyncMock(return_value=logs))

    events, cursors, seen_ids = await coordinator._fetch_pos_events(api, {1: resource})

    assert [event["id"] for event in events] == [10]
    assert events[0] == {
        "id": 10,
        "resource": 1,
        "type": "allowed",
        "createdAt": logs[0]["createdAt"],
        "stoppedAt": None,
        "stopType": None,
    }
    assert cursors["1"] >= now
    assert seen_ids["1"] == {10, 11}
    api.get_resource_logs.assert_awaited_once_with(
        1, (now - timedelta(seconds=11)).isoformat()
    )


async def test_pos_cursor_is_discarded_when_resource_is_inactive(coordinator):
    now = dt_util.utcnow()
    coordinator._pos_cursors = {"1": now - timedelta(days=1)}
    coordinator._pos_seen_ids = {"1": {10}}
    api = SimpleNamespace(get_resource_logs=AsyncMock())

    events, cursors, seen_ids = await coordinator._fetch_pos_events(
        api, {1: {**coordinator.data[1], "controlType": "pos", "state": "archived"}}
    )

    assert events == []
    assert cursors == {}
    assert seen_ids == {}
    api.get_resource_logs.assert_not_awaited()


async def test_nuki_devices_are_fetched_per_valid_space_and_linked(coordinator):
    resources = {
        1: {**coordinator.data[1], "controlType": "nuki", "space": "005", "nukiDeviceId": "0088"},
        2: {**coordinator.data[1], "id": 2, "controlType": "nuki", "space": "../5"},
    }
    device = {"smartlockId": 88, "serverState": 0, "state": {"state": 1}}
    api = SimpleNamespace(get_nuki_devices=AsyncMock(return_value=[device]))

    by_space, failures = await coordinator._fetch_nuki_devices(api, resources)
    coordinator._nuki_devices_by_space = by_space

    api.get_nuki_devices.assert_awaited_once_with("5")
    assert failures == set()
    assert coordinator.nuki_space_available(resources[1])
    assert coordinator.nuki_device(resources[1]) == device
    assert not coordinator.nuki_space_available(resources[2])
