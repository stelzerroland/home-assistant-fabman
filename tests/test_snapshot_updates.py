"""Exercise real coordinator error recovery, ordering and debouncing."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.fabman.api import FabmanAPIError, FabmanRateLimitError
from custom_components.fabman.binary_sensor import FabmanActivitySensor
from custom_components.fabman.switch import FabmanSwitch

from .factories import machine


async def test_active_resource_recovers_without_an_intermediate_off(coordinator):
    sensor = FabmanActivitySensor(coordinator, 1, "first")
    observed = []
    remove = coordinator.async_add_listener(
        lambda: observed.append(sensor.state if sensor.available else "unavailable")
    )
    try:
        with patch(
            "custom_components.fabman.coordinator.FabmanAPI.get_resources",
            new=AsyncMock(
                side_effect=[[machine()], FabmanAPIError("HTTP 503"), [machine()]]
            ),
        ):
            for _ in range(3):
                await coordinator.async_refresh()
    finally:
        remove()
    assert observed == ["on", "unavailable", "on"]


async def test_removed_resource_returns_with_same_entity_and_unique_id(coordinator):
    sensor = FabmanActivitySensor(coordinator, 1, "first")
    unique_id = sensor.unique_id
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=[[machine()], [], [machine()]]),
    ):
        await coordinator.async_refresh()
        assert sensor.available
        await coordinator.async_refresh()
        assert not sensor.available
        await coordinator.async_refresh()
    assert sensor.available
    assert sensor.state == "on"
    assert sensor.unique_id == unique_id


async def test_bad_individual_resources_do_not_disable_valid_resources(coordinator):
    malformed = {**machine(2), "lastUsed": "invalid"}
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(
            return_value=[None, [], {"id": True}, {"id": "1"}, machine(), malformed]
        ),
    ):
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.activity(1).is_on is True
    assert coordinator.activity(2).is_on is None
    assert coordinator.invalid_resource_count == 4
    assert coordinator.resource_count == 6


@pytest.mark.parametrize(
    "resources", [None, {}, [None, {"id": "bad"}], [machine(), machine()]]
)
async def test_unusable_snapshots_fail_without_partial_replacement(
    coordinator, resources
):
    before = deepcopy(coordinator.data)
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=resources),
    ):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.data == before


async def test_older_get_cannot_replace_newer_confirmed_data(coordinator):
    started, finish = asyncio.Event(), asyncio.Event()
    coordinator.async_request_refresh = AsyncMock()

    async def old_get():
        started.set()
        await finish.wait()
        return [machine(active=False)]

    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=old_get),
    ):
        task = asyncio.create_task(coordinator.async_refresh())
        await asyncio.wait_for(started.wait(), timeout=1)
        coordinator.async_set_updated_data({1: machine(active=True)})
        finish.set()
        await task
    assert coordinator.activity(1).is_on is True


async def test_older_failed_get_does_not_invalidate_newer_confirmed_data(coordinator):
    started, finish = asyncio.Event(), asyncio.Event()
    coordinator.async_request_refresh = AsyncMock()

    async def old_get():
        started.set()
        await finish.wait()
        raise FabmanAPIError("Older request failed")

    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=old_get),
    ):
        task = asyncio.create_task(coordinator.async_refresh())
        await asyncio.wait_for(started.wait(), timeout=1)
        coordinator.async_set_updated_data({1: machine()})
        finish.set()
        await task
    assert coordinator.last_update_success
    assert coordinator.activity(1).is_on is True


async def test_command_during_get_keeps_activity_unknown_until_fresh_confirmation(
    coordinator,
):
    started, finish = asyncio.Event(), asyncio.Event()
    coordinator.async_request_refresh = AsyncMock()
    original = deepcopy(coordinator.data)
    switch = FabmanSwitch(coordinator, 1, "machine")

    async def old_get():
        started.set()
        await finish.wait()
        return [machine(active=False)]

    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=old_get),
    ):
        task = asyncio.create_task(coordinator.async_refresh())
        await asyncio.wait_for(started.wait(), timeout=1)
        coordinator.async_note_command(1, True)
        finish.set()
        await task
    assert coordinator.data == original
    assert coordinator.activity(1).is_on is None
    assert switch.is_on is True
    assert switch.assumed_state
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[machine()]),
    ):
        await coordinator.async_refresh()
    assert coordinator.activity(1).is_on is True
    assert not switch.assumed_state


async def test_contradictory_fresh_read_does_not_confirm_a_pending_command(coordinator):
    coordinator.async_note_command(1, True)
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[machine(active=False)]),
    ):
        await coordinator.async_refresh()
    assert coordinator.activity(1).is_on is None
    assert 1 in coordinator.pending_commands


async def test_command_does_not_forge_recovery_after_an_api_failure(coordinator):
    coordinator.last_update_success = False
    coordinator.async_note_command(1, True)
    assert not coordinator.last_update_success


async def test_discarded_read_does_not_forge_recovery_after_command(coordinator):
    coordinator.last_update_success = False
    started, finish = asyncio.Event(), asyncio.Event()
    coordinator.async_request_refresh = AsyncMock()

    async def old_get():
        started.set()
        await finish.wait()
        return [machine()]

    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=old_get),
    ):
        task = asyncio.create_task(coordinator.async_refresh())
        await asyncio.wait_for(started.wait(), timeout=1)
        coordinator.async_note_command(1, True)
        finish.set()
        await task
    assert not coordinator.last_update_success
    assert coordinator.last_successful_fetch is None


async def test_rate_limit_blocks_early_follow_up_network_requests(coordinator):
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=FabmanRateLimitError(120)),
    ) as fetch:
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    fetch.assert_awaited_once()
    assert not coordinator.last_update_success


async def test_transport_exception_text_is_not_logged(coordinator, caplog):
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=RuntimeError("secret-token private-member")),
    ):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert "secret-token" not in caplog.text
    assert "private-member" not in caplog.text


async def test_bursts_use_coordinator_debouncing_without_parallel_fetches(coordinator):
    running = peak = calls = 0
    coordinator._debounced_refresh.cooldown = 0.02

    async def fetch():
        nonlocal running, peak, calls
        calls += 1
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return [machine()]

    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=fetch),
    ):
        await asyncio.gather(*(coordinator.async_request_refresh() for _ in range(30)))
        await asyncio.sleep(0.1)
    assert peak == 1
    assert 1 <= calls <= 2
