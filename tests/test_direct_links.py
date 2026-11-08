"""Opt-in, identity, race and command-correlation tests without real hardware."""

import asyncio
from copy import copy, deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr

from custom_components.fabman.commands import ResourceCommands
from custom_components.fabman.const import CONF_DIRECT_LINK_RESOURCES, DATA_DIRECT_LINKS
from custom_components.fabman.direct_links import (
    CONFIRMATION_TTL,
    DirectLinkError,
    DirectLinks,
    enabled_resources,
)
from custom_components.fabman.frontend import async_setup_panel, async_unload_panel
from custom_components.fabman import websocket
from custom_components.fabman.config_flow import FabmanOptionsFlow

from .factories import machine


@pytest.fixture
async def links(hass, coordinator):
    dr.async_setup(hass)
    await dr.async_load(hass, load_empty=True)
    await er.async_load(hass, load_empty=True)
    entry = SimpleNamespace(
        entry_id="first",
        title="Synthetic Fabman",
        disabled_by=None,
        pref_disable_new_entities=False,
        options={CONF_DIRECT_LINK_RESOURCES: [1]},
    )
    hass.config_entries.async_get_entry.return_value = entry
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "switch", "fabman", "fabman_switch_1", config_entry=entry
    )
    coordinator.async_set_updated_data({1: machine(active=False)})
    coordinator.data[1]["lastUsed"]["id"] = 91
    coordinator.async_refresh = AsyncMock()
    hass.states.async_set(entity.entity_id, "off")
    permissions = Mock(check_entity=Mock(return_value=True))
    user = SimpleNamespace(
        id="employee",
        name="Example Employee",
        is_active=True,
        system_generated=False,
        is_admin=False,
        permissions=permissions,
    )
    hass.auth = Mock(async_get_user=AsyncMock(return_value=user))
    manager = DirectLinks(hass)
    manager.attach(entry)
    hass.data[DATA_DIRECT_LINKS] = manager
    runtime = SimpleNamespace(
        manager=manager,
        entry=entry,
        user=user,
        entity_id=entity.entity_id,
        coordinator=coordinator,
        registry=registry,
    )
    yield runtime
    manager.detach("first")
    tasks = [r.task for r in manager.records.values() if r.task is not None]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def prepare(links):
    return await links.manager.prepare(links.user, "first", 1)


async def execute(links, preview):
    result = links.manager.execute(links.user, preview["confirmation_id"])
    await links.manager.records[result["operation_id"]].task
    return links.manager.status(links.user, result["operation_id"])


@pytest.mark.parametrize(
    "options",
    [
        {},
        {CONF_DIRECT_LINK_RESOURCES: []},
        {CONF_DIRECT_LINK_RESOURCES: True},
        {CONF_DIRECT_LINK_RESOURCES: [True, "1", -1]},
    ],
)
async def test_default_and_malformed_options_never_enable_links(links, options):
    links.entry.options = options
    assert enabled_resources(options) == set()
    with pytest.raises(DirectLinkError, match="unavailable"):
        await prepare(links)
    links.coordinator.async_refresh.assert_not_awaited()


async def test_discovery_never_enables_new_resource(links):
    links.coordinator.data[2] = machine(2)
    with pytest.raises(DirectLinkError, match="unavailable"):
        await links.manager.prepare(links.user, "first", 2)
    assert enabled_resources(links.entry.options) == {1}


@pytest.mark.parametrize(
    "change",
    ["inactive", "system", "no_read", "no_control", "wrong_entry", "disabled_entity"],
)
async def test_identity_and_entity_permissions_checked_before_api(links, change):
    if change == "inactive":
        links.user.is_active = False
    elif change == "system":
        links.user.system_generated = True
    elif change in ("no_read", "no_control"):
        links.user.permissions.check_entity.side_effect = (
            (lambda entity_id, policy: policy == POLICY_CONTROL)
            if change == "no_read"
            else (lambda entity_id, policy: policy != POLICY_CONTROL)
        )
    elif change == "wrong_entry":
        links.registry.async_update_entity(links.entity_id, config_entry_id="second")
    else:
        links.registry.async_update_entity(
            links.entity_id, disabled_by=er.RegistryEntryDisabler.USER
        )
    with pytest.raises(DirectLinkError, match="unauthorized"):
        await prepare(links)
    links.coordinator.async_refresh.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "offline",
        "archived",
        "missing",
        "pos",
        "nuki",
        "pending",
        "failed_read",
    ],
)
async def test_untrusted_machine_state_cannot_prepare(links, change):
    c = links.coordinator
    if change == "unknown":
        c.data[1]["lastUsed"] = None
    elif change == "offline":
        c.data[1]["_embedded"]["bridge"]["offline"] = True
    elif change == "archived":
        c.data[1]["state"] = "archived"
    elif change == "missing":
        c.data = {}
    elif change in ("pos", "nuki"):
        c.data[1]["controlType"] = change
    elif change == "pending":
        c.async_note_command(1, True)
    else:
        c.last_update_success = False
    with pytest.raises(DirectLinkError):
        await prepare(links)


async def test_never_used_door_has_open_action_not_toggle(links):
    links.coordinator.data[1].update(controlType="door", lastUsed=None)
    preview = await prepare(links)
    assert preview["action"] == "open" and preview["is_on"] is None


async def test_mapped_preview_exposes_only_minimal_identity(links):
    links.coordinator.user_member_map[links.user.id] = 8
    links.entry.options["user_member_map"] = {links.user.id: 8}
    with patch("custom_components.fabman.direct_links.MemberAssignment") as factory:
        worker = factory.return_value
        worker.resolve_member = AsyncMock(return_value=8)
        worker.member_name = "Example Member"
        result = await prepare(links)
    worker.resolve_member.assert_awaited_once_with(member_id=8)
    assert result["member_name"] == "Example Member" and result["member_id"] == 8
    assert "emailAddress" not in result and "api_token" not in result


async def test_invalid_mapping_has_no_api_key_fallback(links):
    links.coordinator.user_member_map[links.user.id] = 8
    links.entry.options["user_member_map"] = {links.user.id: 8}
    with patch("custom_components.fabman.direct_links.MemberAssignment") as factory:
        factory.return_value.resolve_member = AsyncMock(
            side_effect=HomeAssistantError("not found")
        )
        with pytest.raises(DirectLinkError, match="invalid_mapping"):
            await prepare(links)
    assert not links.manager.records


async def test_revocation_invalidates_an_open_confirmation(links):
    preview = await prepare(links)
    links.entry.options = {}
    with pytest.raises(DirectLinkError, match="unavailable"):
        links.manager.execute(links.user, preview["confirmation_id"])


async def test_confirmation_bound_to_user_and_expiry(links):
    preview = await prepare(links)
    other = deepcopy(links.user)
    other.id = "different"
    with pytest.raises(DirectLinkError, match="expired"):
        links.manager.execute(other, preview["confirmation_id"])
    links.manager.records[preview["confirmation_id"]].created -= CONFIRMATION_TTL + 1
    with pytest.raises(DirectLinkError, match="expired"):
        links.manager.execute(links.user, preview["confirmation_id"])


@pytest.mark.parametrize(
    "change",
    ["on", "new_usage", "mapping", "type", "revoked", "removed_user", "permission"],
)
async def test_execute_rechecks_intent_before_post(links, change):
    preview = await prepare(links)
    if change == "on":
        links.coordinator.data[1] = machine(active=True)
    elif change == "new_usage":
        links.coordinator.data[1]["lastUsed"]["id"] = 92
    elif change == "mapping":
        links.coordinator.user_member_map[links.user.id] = 8
    elif change == "type":
        links.coordinator.data[1]["controlType"] = "door"
    elif change == "revoked":
        links.coordinator.async_refresh.side_effect = lambda: setattr(
            links.entry, "options", {}
        )
    elif change == "removed_user":
        links.manager.hass.auth.async_get_user.return_value = None
    else:
        links.coordinator.async_refresh.side_effect = lambda: setattr(
            links.user.permissions.check_entity, "return_value", False
        )
    session = Mock()
    with patch(
        "custom_components.fabman.commands.async_get_clientsession",
        return_value=session,
    ):
        if change == "permission":
            with pytest.raises(DirectLinkError, match="unauthorized"):
                await execute(links, preview)
            record = links.manager.records[preview["confirmation_id"]]
            await record.task
            result = {"phase": record.phase}
        else:
            result = await execute(links, preview)
    session.post.assert_not_called()
    assert result["phase"] == "blocked"


async def test_single_submission_and_command_specific_confirmation(links):
    preview = await prepare(links)
    entered, release = asyncio.Event(), asyncio.Event()

    async def post_guarded(executor, is_on, *, member_id=None):
        async with links.coordinator.dispatch_locks[1]:
            await executor._before_send()
            entered.set()
            await release.wait()
            command = links.coordinator.async_note_command(1, is_on)
            executor._on_sent(command)

    with patch.object(ResourceCommands, "_async_send_command", post_guarded):
        first = links.manager.execute(links.user, preview["confirmation_id"])
        await entered.wait()
        second = links.manager.execute(links.user, preview["confirmation_id"])
        assert first["operation_id"] == second["operation_id"]
        release.set()
        await links.manager.records[first["operation_id"]].task
    result = links.manager.status(links.user, first["operation_id"])
    assert result["phase"] == "accepted" and result["command_status"] == "pending"
    # An unrelated newer command must not confirm this operation.
    links.coordinator.async_note_command(1, False)
    assert (
        links.manager.status(links.user, first["operation_id"])["command_status"]
        == "superseded"
    )


@pytest.mark.parametrize(
    "status,expected", [(201, "accepted"), (422, "rejected"), (500, "rejected")]
)
async def test_real_http_request_runs_once_and_omits_member_without_mapping(
    links, status, expected
):
    calls = []

    async def handler(request):
        calls.append(await request.json())
        return web.json_response({}, status=status)

    app = web.Application()
    app.router.add_post("/resources/1/bridge/switch-on", handler)
    async with TestClient(TestServer(app)) as client:
        links.coordinator.api_url = str(client.make_url("/")).rstrip("/")
        preview = await prepare(links)
        with patch(
            "custom_components.fabman.commands.async_get_clientsession",
            return_value=client.session,
        ):
            result = await execute(links, preview)
            duplicate = links.manager.execute(links.user, preview["confirmation_id"])
        assert result["phase"] == expected and duplicate["phase"] == expected
    assert calls == [{}]


@pytest.mark.parametrize("attribution_ok", [True, False])
async def test_real_mapped_activation_preserves_user_and_member_confirmation(
    links, attribution_ok
):
    links.coordinator.user_member_map[links.user.id] = 8
    links.entry.options["user_member_map"] = {links.user.id: 8}
    requests = []

    async def handler(request):
        requests.append((request.method, request.path))
        if request.path == "/members/8":
            return web.json_response(
                {"id": 8, "account": 42, "firstName": "Test", "lastName": "Member"}
            )
        if request.path == "/resources/1":
            return web.json_response(links.coordinator.data[1])
        if request.method == "POST":
            assert await request.json() == {"member": 8}
            return web.json_response({}, status=201)
        return web.json_response({}, status=404)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    async with TestClient(TestServer(app)) as client:
        links.coordinator.api_url = str(client.make_url("/")).rstrip("/")
        links.coordinator._session = client.session
        preview = await prepare(links)
        assert preview["member_name"] == "Test Member"
        with (
            patch(
                "custom_components.fabman.commands.async_get_clientsession",
                return_value=client.session,
            ),
            patch(
                "custom_components.fabman.commands.MemberAssignment.confirm_direct_member",
                new=AsyncMock(
                    side_effect=None if attribution_ok else HomeAssistantError("no log")
                ),
            ),
            patch.object(links.coordinator, "async_request_refresh", new=AsyncMock()),
        ):
            result = await execute(links, preview)
    assert result["member_status"] == ("assigned" if attribution_ok else "failed")
    assert result["phase"] == "accepted"
    assert links.coordinator.last_activations[1]["ha_user_id"] == links.user.id
    assert links.coordinator.last_activations[1]["assigned_member_id"] == (
        8 if attribution_ok else None
    )
    assert sum(method == "POST" for method, _ in requests) == 1


async def test_timeout_and_late_observation_are_correlated_to_same_command(links):
    command = links.coordinator.async_note_command(1, True)
    links.coordinator._command_timed_out(1, command)
    assert links.coordinator.command_outcomes[command.command_id] == "timeout"
    links.coordinator.async_set_updated_data({1: machine(active=True)})
    assert links.coordinator.command_outcomes[command.command_id] == "confirmed"


async def test_two_users_cannot_send_same_stale_action(links):
    one, two = await prepare(links), await prepare(links)
    posts = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        posts.append(await request.json())
        entered.set()
        await release.wait()
        return web.json_response({}, status=201)

    app = web.Application()
    app.router.add_post("/resources/1/bridge/switch-on", handler)
    async with TestClient(TestServer(app)) as client:
        links.coordinator.api_url = str(client.make_url("/")).rstrip("/")
        with patch(
            "custom_components.fabman.commands.async_get_clientsession",
            return_value=client.session,
        ):
            links.manager.execute(links.user, one["confirmation_id"])
            await entered.wait()
            links.manager.execute(links.user, two["confirmation_id"])
            release.set()
            await asyncio.gather(*(r.task for r in links.manager.records.values()))
    assert posts == [{}]
    assert (
        links.manager.status(links.user, two["confirmation_id"])["phase"] == "blocked"
    )


async def test_reload_invalidates_confirmation_and_new_manager_cannot_replay(links):
    preview = await prepare(links)
    links.manager.detach("first")
    with pytest.raises(DirectLinkError):
        links.manager.execute(links.user, preview["confirmation_id"])
    new_manager = DirectLinks(links.manager.hass)
    with pytest.raises(DirectLinkError, match="expired"):
        new_manager.execute(links.user, preview["confirmation_id"])


async def test_admin_only_link_list_excludes_disabled_resources(links):
    with pytest.raises(DirectLinkError, match="unauthorized"):
        links.manager.list_links(links.user)
    links.user.is_admin = True
    links.coordinator.data[2] = machine(2)
    items = links.manager.list_links(links.user)
    assert len(items) == 1 and items[0]["path"] == "/fabman/qr/first/1"
    links.entry.options = {}
    assert links.manager.list_links(links.user) == []


async def test_panel_registration_reload_and_multi_entry_cleanup(hass):
    hass.http = Mock(async_register_static_paths=AsyncMock())
    first, second = (
        SimpleNamespace(entry_id="first"),
        SimpleNamespace(entry_id="second"),
    )
    with (
        patch("custom_components.fabman.frontend.async_register") as register,
        patch(
            "custom_components.fabman.frontend.panel_custom.async_register_panel",
            new=AsyncMock(),
        ) as panel,
        patch(
            "custom_components.fabman.frontend.frontend.async_remove_panel"
        ) as remove,
    ):
        await asyncio.gather(
            async_setup_panel(hass, first), async_setup_panel(hass, second)
        )
        register.assert_called_once()
        panel.assert_awaited_once()
        hass.http.async_register_static_paths.assert_awaited_once()
        async_unload_panel(hass, "first")
        remove.assert_not_called()
        async_unload_panel(hass, "second")
        remove.assert_called_once()
        await async_setup_panel(hass, first)
        assert panel.await_count == 2
        register.assert_called_once()
        hass.http.async_register_static_paths.assert_awaited_once()


async def test_websocket_uses_connection_identity_and_rejects_extra_selectors(links):
    handler = websocket.prepare
    # Schema must reject forged identities, members and unknown fields.
    for extra in ({"user_id": "admin"}, {"member_id": 8}):
        with pytest.raises(Exception):
            handler._ws_schema(
                {
                    "id": 1,
                    "type": "fabman/direct_link/prepare",
                    "entry_id": "first",
                    "resource_id": 1,
                    **extra,
                }
            )
    connection = Mock(user=links.user)
    connection.context.return_value = SimpleNamespace(user_id=links.user.id)
    await handler.__wrapped__(
        links.manager.hass,
        connection,
        {
            "id": 1,
            "type": "fabman/direct_link/prepare",
            "entry_id": "first",
            "resource_id": 1,
        },
    )
    connection.send_result.assert_called_once()
    record = next(iter(links.manager.records.values()))
    assert record.user_id == links.user.id


async def test_options_default_off_enable_revoke_and_preserve_mappings(links):
    hass = links.manager.hass
    hass.config_entries.async_get_known_entry.return_value = links.entry
    flow = FabmanOptionsFlow()
    flow.hass = hass
    flow.handler = "first"
    links.entry.options = {"user_member_map": {"employee": 8}}
    result = await flow.async_step_direct_links()
    schema = result["data_schema"]
    assert schema({})[CONF_DIRECT_LINK_RESOURCES] == []
    result = await flow.async_step_direct_links({CONF_DIRECT_LINK_RESOURCES: ["1"]})
    assert result["data"][CONF_DIRECT_LINK_RESOURCES] == [1]
    assert result["data"]["user_member_map"] == {"employee": 8}
    links.entry.options = result["data"]
    result = await flow.async_step_direct_links({CONF_DIRECT_LINK_RESOURCES: []})
    assert result["data"][CONF_DIRECT_LINK_RESOURCES] == []
    assert result["data"]["user_member_map"] == {"employee": 8}
    invalid = await flow.async_step_direct_links({CONF_DIRECT_LINK_RESOURCES: ["99"]})
    assert invalid["errors"] == {"base": "invalid_resource"}
    mapping_edit = flow._save_mappings({"employee": 9})
    assert mapping_edit["data"][CONF_DIRECT_LINK_RESOURCES] == [1]


async def test_reload_during_final_refresh_cannot_send_on_old_coordinator(links):
    preview = await prepare(links)
    calls = 0

    async def refresh():
        nonlocal calls
        calls += 1
        if calls == 2:
            links.manager.hass.data["fabman"]["first"] = copy(links.coordinator)

    links.coordinator.async_refresh.side_effect = refresh
    session = Mock()
    with patch(
        "custom_components.fabman.commands.async_get_clientsession",
        return_value=session,
    ):
        result = await execute(links, preview)
    session.post.assert_not_called()
    assert result["phase"] == "blocked"


async def test_confirmation_expiring_during_final_read_cannot_send(links):
    preview = await prepare(links)
    record = links.manager.records[preview["confirmation_id"]]
    links.coordinator.async_refresh.side_effect = lambda: setattr(
        record, "created", record.created - CONFIRMATION_TTL - 1
    )
    session = Mock()
    with patch(
        "custom_components.fabman.commands.async_get_clientsession",
        return_value=session,
    ):
        result = await execute(links, preview)
    session.post.assert_not_called()
    assert result["error"] == "expired"


async def test_mapping_option_change_before_reload_blocks_activation(links):
    preview = await prepare(links)
    links.entry.options["user_member_map"] = {links.user.id: 8}
    session = Mock()
    with patch(
        "custom_components.fabman.commands.async_get_clientsession",
        return_value=session,
    ):
        result = await execute(links, preview)
    session.post.assert_not_called()
    assert result["error"] == "changed"


@pytest.mark.parametrize(
    "handler,msg",
    [
        (websocket.prepare, {"entry_id": "first"}),
        (websocket.prepare, {"resource_id": 1}),
        (websocket.execute, {}),
        (websocket.status, {}),
    ],
)
def test_websocket_requires_complete_requests(handler, msg):
    import probatio

    with pytest.raises(probatio.Invalid):
        handler._ws_schema({"id": 1, "type": handler._ws_command, **msg})


async def test_panel_registers_real_ha_panel_and_gateway(hass):
    from homeassistant.components import frontend as ha_frontend

    hass.http = Mock(async_register_static_paths=AsyncMock())
    await async_setup_panel(hass, SimpleNamespace(entry_id="first"))
    assert ha_frontend.async_panel_exists(hass, "fabman")
    assert set(hass.data["websocket_api"]) >= {
        "fabman/direct_link/prepare",
        "fabman/direct_link/execute",
        "fabman/direct_link/status",
        "fabman/direct_link/list",
    }
    config = hass.data["frontend_panels"]["fabman"].config
    assert config["_panel_custom"]["module_url"].startswith("/fabman_static/")
    async_unload_panel(hass, "first")
    assert not ha_frontend.async_panel_exists(hass, "fabman")


async def test_transport_failure_is_uncertain_and_never_retried(links):
    from aiohttp import ClientConnectionError

    preview = await prepare(links)
    session = Mock()
    session.post.side_effect = ClientConnectionError("sensitive transport detail")
    with patch(
        "custom_components.fabman.commands.async_get_clientsession",
        return_value=session,
    ):
        result = await execute(links, preview)
        links.manager.execute(links.user, preview["confirmation_id"])
    assert result["phase"] == "uncertain"
    assert "sensitive" not in str(result)
    assert session.post.call_count == 1


async def test_reload_cancels_queued_activation_before_post(links):
    preview = await prepare(links)
    session = Mock()
    with patch(
        "custom_components.fabman.commands.async_get_clientsession",
        return_value=session,
    ):
        async with links.coordinator.command_locks[1]:
            links.manager.execute(links.user, preview["confirmation_id"])
            await asyncio.sleep(0)
            links.manager.detach("first")
            record = links.manager.records[preview["confirmation_id"]]
            await record.task
    session.post.assert_not_called()
    assert record.phase == "interrupted"


async def test_reload_retains_already_confirmed_result(links):
    preview = await prepare(links)

    async def send(executor, is_on, *, member_id=None):
        await executor._before_send()
        command = links.coordinator.async_note_command(1, is_on)
        executor._on_sent(command)
        links.coordinator.async_set_updated_data({1: machine(active=True)})

    with patch.object(ResourceCommands, "_async_send_command", send):
        result = await execute(links, preview)
    assert result["command_status"] == "confirmed"
    links.manager.detach("first")
    assert (
        links.manager.status(links.user, result["operation_id"])["command_status"]
        == "confirmed"
    )
    assert (
        links.manager.status(links.user, result["operation_id"])["phase"] == "accepted"
    )
