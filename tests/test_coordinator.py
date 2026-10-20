"""Door expiry and delayed refresh lifecycle tests."""

import asyncio
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


async def test_door_expiry_notifies_entities_without_polling(coordinator):
    coordinator.data[1].update(controlType="door", maxOfflineUsage=0.02)
    listener = Mock()
    remove_listener = coordinator.async_add_listener(listener)
    coordinator.async_request_refresh = AsyncMock()
    try:
        coordinator.async_set_resource_status(1, True)
        listener.reset_mock()
        await asyncio.sleep(0.05)
        listener.assert_called_once()
        coordinator.async_request_refresh.assert_awaited_once()
        assert not coordinator._door_timers
    finally:
        remove_listener()


async def test_cancel_pending_updates_prevents_late_refresh(coordinator):
    coordinator.data[1].update(controlType="door", maxOfflineUsage=0.02)
    coordinator.async_set_resource_status(1, True)
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
