"""Exercise attribution without switching real hardware or editing real usage."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
import voluptuous as vol
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.fabman.assignment import MemberAssignment
from custom_components.fabman.switch import FabmanSwitch, async_setup_entry

START = "2026-10-21T10:00:00Z"
END = "2026-10-21T10:00:02Z"


def command(**changes):
    return dict(
        id=51,
        account=42,
        resource=1,
        type="activate",
        member=7,
        state="done",
        createdAt=START,
        updatedAt=END,
        **changes,
    )


def usage(**changes):
    result = dict(
        id=91,
        account=42,
        resource=1,
        type="allowed",
        member=7,
        createdAt="2026-10-21T10:00:01Z",
        lockVersion=3,
    )
    result.update(changes)
    return result


@pytest.fixture
def assignment(coordinator):
    result = MemberAssignment(Mock(), coordinator, 1)
    result.request = AsyncMock()
    return result


@pytest.mark.parametrize(
    "selector", [{"member_id": 8}, {"email_address": "Member@Example.com "}]
)
async def test_resolve_exact_account_member(assignment, selector):
    member = dict(id=8, account=42, emailAddress="member@example.com")
    assignment.request.return_value = member if "member_id" in selector else [member]
    assert await assignment.resolve_member(**selector) == 8


@pytest.mark.parametrize(
    "selector,response",
    [
        ({"member_id": True}, None),
        ({"member_id": 0}, None),
        ({"member_id": 8, "email_address": "x@example.com"}, None),
        ({"member_id": 8}, {"id": 8, "account": 99}),
        ({"member_id": 8}, {"id": 9, "account": 42}),
        ({"email_address": "x@example.com"}, []),
        (
            {"email_address": "x@example.com"},
            [{"id": 8, "account": 42, "emailAddress": "other@example.com"}],
        ),
        ({"email_address": "x@example.com"}, [{"id": 8}, {"id": 9}]),
        ({"email_address": " "}, None),
    ],
)
async def test_invalid_member_aborts_before_activation(assignment, selector, response):
    assignment.request.return_value = response
    with pytest.raises(HomeAssistantError):
        await assignment.resolve_member(**selector)


async def test_confirmed_usage_changes_only_member_with_fresh_version(assignment):
    assignment.request.side_effect = [[usage()], usage(lockVersion=4), usage(member=8)]
    await assignment.assign(command(), 8, 90)
    assert assignment.request.call_args_list[-1].args == ("PUT", "resource-logs/91")
    assert assignment.request.call_args_list[-1].kwargs["data"] == {
        "member": 8,
        "lockVersion": 4,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"id": 90},
        {"resource": 2},
        {"account": 99},
        {"member": 10},
        {"type": "denied"},
        {"createdAt": START.replace("10:", "09:")},
        {"createdAt": "2026-10-21T10:00:03Z"},
        {"createdAt": "invalid"},
        {"createdAt": "2026-10-21T10:00:01"},
    ],
)
async def test_unrelated_logs_never_updated(assignment, changes):
    assignment.request.return_value = [usage(**changes)]
    with pytest.raises(HomeAssistantError):
        await assignment.assign(command(), 8, 90)
    assert all(c.args[0] != "PUT" for c in assignment.request.call_args_list)


@pytest.mark.parametrize("logs", [[], [usage(), usage(id=92)]])
async def test_missing_or_ambiguous_usage_fails_closed(assignment, logs):
    assignment.request.return_value = logs
    with pytest.raises(HomeAssistantError, match="unique"):
        await assignment.assign(command(), 8, 90)


async def test_concurrent_member_change_not_overwritten(assignment):
    assignment.request.side_effect = [[usage()], usage(member=9)]
    with pytest.raises(HomeAssistantError, match="changed"):
        await assignment.assign(command(), 8, 90)
    assert assignment.request.await_count == 2


async def test_failed_command_never_edits_usage(assignment):
    failed = command()
    failed["error"] = "offline"
    with pytest.raises(HomeAssistantError, match="successful"):
        await assignment.assign(failed, 8, 90)
    assignment.request.assert_not_called()


async def test_pending_command_is_polled_without_reactivation(assignment):
    pending = command()
    pending["state"] = "pending"
    assignment.request.side_effect = [command(), [usage()], usage(), usage(member=8)]
    with patch("custom_components.fabman.assignment.asyncio.sleep", new=AsyncMock()):
        await assignment.assign(pending, 8, 90)
    assert assignment.request.call_args_list[0].args == ("GET", "bridge-commands/51")
    assert all(c.args[0] != "POST" for c in assignment.request.call_args_list)


async def test_http_conflict_and_sensitive_body_are_not_exposed(coordinator):
    async def conflict(request):
        assert await request.json() == {"member": 8, "lockVersion": 3}
        return web.json_response({"secret": "private details"}, status=409)

    app = web.Application()
    app.router.add_put("/resource-logs/91", conflict)
    async with TestClient(TestServer(app)) as client:
        coordinator.api_url = str(client.make_url("/")).rstrip("/")
        real = MemberAssignment(client.session, coordinator, 1)
        with pytest.raises(HomeAssistantError, match="HTTP 409") as error:
            await real.request(
                "PUT", "resource-logs/91", data={"member": 8, "lockVersion": 3}
            )
        assert "private" not in str(error.value)


async def test_default_action_keeps_existing_behavior(coordinator):
    entity = FabmanSwitch(coordinator, 1, "machine")
    with patch.object(entity, "_async_send_command", new=AsyncMock()) as send:
        await entity.async_turn_on_for_member()
    send.assert_awaited_once_with(True)


async def test_assignment_failure_keeps_accepted_state_without_second_post(coordinator):
    entity = FabmanSwitch(coordinator, 1, "machine")
    baseline = deepcopy(coordinator.data[1])
    with (
        patch(
            "custom_components.fabman.switch.async_get_clientsession",
            return_value=Mock(),
        ),
        patch("custom_components.fabman.switch.MemberAssignment") as factory,
        patch.object(
            entity, "_async_send_command", new=AsyncMock(return_value=command())
        ) as send,
    ):
        worker = factory.return_value
        worker.account = 42
        worker.resolve_member = AsyncMock(return_value=8)
        worker.request = AsyncMock(return_value=baseline)
        worker.assign = AsyncMock(side_effect=HomeAssistantError("conflict"))
        with pytest.raises(HomeAssistantError, match="activation was accepted"):
            await entity.async_turn_on_for_member(member_id=8)
        send.assert_awaited_once_with(True, read_command=True)
        worker.assign.assert_awaited_once()


async def test_normal_activation_waits_for_member_assignment_lock(coordinator):
    entity = FabmanSwitch(coordinator, 1, "machine")
    async with coordinator.command_locks[1]:
        with patch.object(entity, "_async_send_command", new=AsyncMock()) as send:
            task = asyncio.create_task(entity.async_turn_on())
            await asyncio.sleep(0)
            send.assert_not_called()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_stop_does_not_wait_for_member_assignment(coordinator):
    entity = FabmanSwitch(coordinator, 1, "machine")
    async with coordinator.command_locks[1]:
        with patch.object(entity, "_async_send_command", new=AsyncMock()) as send:
            await asyncio.wait_for(entity.async_turn_off(), timeout=0.5)
            send.assert_awaited_once_with(False)


async def test_member_edit_does_not_extend_door_release(coordinator):
    now = dt_util.utcnow()
    resource = coordinator.data[1]
    resource.update(controlType="door", maxOfflineUsage=3)
    resource["lastUsed"] = {"id": 91, "type": "allowed", "at": now.isoformat()}
    created = (now - timedelta(seconds=10)).isoformat()
    coordinator.async_note_assigned_door_grant(1, {"id": 91, "createdAt": created})
    assert coordinator.activity(1).is_on is False
    assert not coordinator._door_timers
    # Raw API data remains untouched; a genuinely new grant uses its own time.
    assert resource["lastUsed"]["at"] == now.isoformat()
    resource["lastUsed"]["id"] = 92
    assert coordinator.activity(1).is_on is True


async def test_service_schema_rejects_both_selectors(hass, coordinator):
    entry = Mock(entry_id="first")
    await async_setup_entry(hass, entry, Mock())
    schema = hass.services.async_services()["fabman"]["turn_on"].schema
    with pytest.raises(vol.Invalid):
        schema(
            {
                "entity_id": "switch.test",
                "member_id": 8,
                "email_address": "x@example.com",
            }
        )
    assert schema({"entity_id": "switch.test", "member_id": 8})["member_id"] == 8


@pytest.mark.parametrize("control_type", ["door", "machine"])
async def test_full_http_member_action_posts_once_and_reassigns(
    coordinator, control_type
):
    calls = []
    baseline = deepcopy(coordinator.data[1])
    baseline["controlType"] = control_type
    coordinator.data[1] = baseline
    log = usage()

    async def handler(request):
        calls.append((request.method, request.path))
        assert request.headers["Authorization"] == "Bearer test-token"
        path = request.path
        if path == "/members/8":
            return web.json_response({"id": 8, "account": 42})
        if path == "/resources/1":
            return web.json_response(baseline)
        if path.endswith("/switch-on"):
            assert await request.json() == {}
            return web.json_response(command(), status=201)
        if path == "/resource-logs":
            assert request.query["resource"] == "1"
            return web.json_response([log])
        if request.method == "PUT":
            assert await request.json() == {"member": 8, "lockVersion": 3}
            log["member"] = 8
        return web.json_response(log)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    async with TestClient(TestServer(app)) as client:
        coordinator.api_url = str(client.make_url("/")).rstrip("/")
        entity = FabmanSwitch(coordinator, 1, control_type)
        with (
            patch(
                "custom_components.fabman.switch.async_get_clientsession",
                return_value=client.session,
            ),
            patch.object(coordinator, "async_request_refresh", new=AsyncMock()),
        ):
            await entity.async_turn_on_for_member(member_id=8)
        assert log["member"] == 8
        assert sum(method == "POST" for method, path in calls) == 1
        assert sum(method == "PUT" for method, path in calls) == 1
        assert entity.assumed_state
