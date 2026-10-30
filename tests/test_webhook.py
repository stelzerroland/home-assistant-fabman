"""Multi-entry routing and unload regression tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.fabman import (
    WEBHOOK_ID,
    async_setup_entry,
    async_unload_entry,
    entry_webhook_id,
    handle_webhook,
)
from custom_components.fabman.const import DOMAIN


def entry(entry_id):
    return SimpleNamespace(entry_id=entry_id, data={"api_token": "test"}, options={})


def fake_coordinator():
    return Mock(
        async_config_entry_first_refresh=AsyncMock(),
        async_request_refresh=AsyncMock(),
        last_update_success=True,
    )


async def test_entry_specific_webhook_refreshes_only_its_account(hass):
    first, second = fake_coordinator(), fake_coordinator()
    hass.data[DOMAIN] = {"first": first, "second": second}
    request = Mock(json=AsyncMock(return_value={"details": {"resource": {"id": 1}}}))
    response = await handle_webhook(hass, entry_webhook_id("second"), request)
    assert response.status == 200
    first.async_request_refresh.assert_not_awaited()
    second.async_request_refresh.assert_awaited_once()


async def test_legacy_webhook_refreshes_all_accounts_and_accepts_test_events(hass):
    first, second = fake_coordinator(), fake_coordinator()
    hass.data[DOMAIN] = {"first": first, "second": second}
    response = await handle_webhook(
        hass, WEBHOOK_ID, Mock(json=AsyncMock(return_value={}))
    )
    assert response.status == 200
    first.async_request_refresh.assert_awaited_once()
    second.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize("payload", [None, [], "invalid"])
async def test_malformed_payload_is_rejected_before_refresh(hass, payload):
    coordinator = fake_coordinator()
    hass.data[DOMAIN] = {"first": coordinator}
    response = await handle_webhook(
        hass, WEBHOOK_ID, Mock(json=AsyncMock(return_value=payload))
    )
    assert response.status == 400
    coordinator.async_request_refresh.assert_not_awaited()


async def test_invalid_json_is_rejected(hass):
    response = await handle_webhook(
        hass, WEBHOOK_ID, Mock(json=AsyncMock(side_effect=ValueError("bad json")))
    )
    assert response.status == 400


async def test_failed_refresh_does_not_prevent_other_accounts(hass):
    first, second = fake_coordinator(), fake_coordinator()
    first.async_request_refresh.side_effect = RuntimeError("API unavailable")
    hass.data[DOMAIN] = {"first": first, "second": second}
    response = await handle_webhook(
        hass, WEBHOOK_ID, Mock(json=AsyncMock(return_value={}))
    )
    assert response.status == 503
    second.async_request_refresh.assert_awaited_once()


async def test_coordinator_update_failure_returns_retryable_status(hass):
    coordinator = fake_coordinator()
    coordinator.last_update_success = False
    hass.data[DOMAIN] = {"first": coordinator}
    response = await handle_webhook(
        hass, WEBHOOK_ID, Mock(json=AsyncMock(return_value={}))
    )
    assert response.status == 503


async def test_multiple_entries_register_distinct_hooks_and_unload_independently(hass):
    first, second = fake_coordinator(), fake_coordinator()
    with (
        patch(
            "custom_components.fabman.FabmanDataUpdateCoordinator",
            side_effect=[first, second],
        ),
        patch("custom_components.fabman.async_register") as register,
        patch("custom_components.fabman.async_unregister") as unregister,
    ):
        await async_setup_entry(hass, entry("first"))
        await async_setup_entry(hass, entry("second"))
        assert [call.args[3] for call in register.call_args_list] == [
            entry_webhook_id("first"),
            WEBHOOK_ID,
            entry_webhook_id("second"),
        ]
        assert await async_unload_entry(hass, entry("first"))
        unregister.assert_called_once_with(hass, entry_webhook_id("first"))
        first.async_cancel_pending_updates.assert_called_once()
        second.async_cancel_pending_updates.assert_not_called()
        assert "second" in hass.data[DOMAIN]
        assert await async_unload_entry(hass, entry("second"))
        unregister.assert_any_call(hass, WEBHOOK_ID)


async def test_failed_unload_keeps_callbacks_and_coordinator(hass):
    coordinator = fake_coordinator()
    hass.data[DOMAIN] = {"first": coordinator}
    hass.config_entries.async_unload_platforms.return_value = False
    with patch("custom_components.fabman.async_unregister") as unregister:
        assert not await async_unload_entry(hass, entry("first"))
    unregister.assert_not_called()
    coordinator.async_cancel_pending_updates.assert_not_called()
    assert hass.data[DOMAIN]["first"] is coordinator


async def test_failed_platform_setup_cleans_its_hooks_and_timers(hass):
    coordinator = fake_coordinator()
    hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError(
        "setup failed"
    )
    with (
        patch(
            "custom_components.fabman.FabmanDataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.fabman.async_register"),
        patch("custom_components.fabman.async_unregister") as unregister,
        pytest.raises(RuntimeError, match="setup failed"),
    ):
        await async_setup_entry(hass, entry("first"))
    assert not hass.data[DOMAIN]
    coordinator.async_cancel_pending_updates.assert_called_once()
    unregister.assert_any_call(hass, entry_webhook_id("first"))
    unregister.assert_any_call(hass, WEBHOOK_ID)


async def test_concurrent_setup_failure_preserves_legacy_hook_for_other_entry(hass):
    first, second = fake_coordinator(), fake_coordinator()
    first_setup_started = asyncio.Event()
    second_setup_finished = asyncio.Event()

    async def forward(config_entry, platforms):
        if config_entry.entry_id == "first":
            first_setup_started.set()
            await second_setup_finished.wait()
            raise RuntimeError("first setup failed")

    hass.config_entries.async_forward_entry_setups.side_effect = forward
    with (
        patch(
            "custom_components.fabman.FabmanDataUpdateCoordinator",
            side_effect=[first, second],
        ),
        patch("custom_components.fabman.async_register"),
        patch("custom_components.fabman.async_unregister") as unregister,
    ):
        first_task = asyncio.create_task(async_setup_entry(hass, entry("first")))
        await first_setup_started.wait()
        try:
            await async_setup_entry(hass, entry("second"))
        finally:
            second_setup_finished.set()
        with pytest.raises(RuntimeError, match="first setup failed"):
            await first_task
    unregister.assert_called_once_with(hass, entry_webhook_id("first"))
    assert hass.data[DOMAIN] == {"second": second}
