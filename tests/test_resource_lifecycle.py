"""Dynamic resources exercise real HA platforms and registries without production writes."""

import asyncio
import logging
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.fabman import (
    async_remove_config_entry_device,
    binary_sensor,
    event,
    sensor,
    switch,
)
from custom_components.fabman.binary_sensor import FabmanNukiLockSensor
from custom_components.fabman.event import FabmanPOSEvent
from custom_components.fabman.sensor import FabmanNukiBatterySensor
from custom_components.fabman.api import FabmanAPIError

from .factories import machine
from .test_presence import BASE, SCOPE, attendance, terminal
from custom_components.fabman.presence import SpacePresence, parse_session
from custom_components.fabman.event import FabmanCheckInActivityEvent
from custom_components.fabman.sensor import FabmanCheckedInMembersSensor


async def test_member_action_routes_to_fabman_switch(runtime, coordinator, hass):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    entity = runtime.entities()["fabman_switch_1"]
    with patch.object(entity, "async_turn_on_for_member", new=AsyncMock()) as turn_on:
        await hass.services.async_call(
            "fabman",
            "turn_on",
            {"entity_id": entity.entity_id, "email_address": "member@example.com"},
            blocking=True,
        )
        turn_on.assert_awaited_once_with(
            member_id=None,
            email_address="member@example.com",
            user_id=None,
        )


@pytest.fixture
async def runtime(hass, coordinator):
    dr.async_setup(hass)
    await dr.async_load(hass, load_empty=True)
    await er.async_load(hass, load_empty=True)
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain="fabman",
        entry_id="first",
        title="Synthetic",
        source="user",
        data={},
        options={},
        unique_id=None,
        discovery_keys={},
        subentries_data=None,
    )
    hass.config_entries.async_get_entry.return_value = entry
    platforms = {}
    tasks = []

    async def flush():
        while tasks:
            pending = tasks[:]
            tasks.clear()
            await asyncio.gather(*pending)
        await hass.async_block_till_done()

    async def setup():
        for domain, module in (
            ("binary_sensor", binary_sensor),
            ("sensor", sensor),
            ("switch", switch),
            ("event", event),
        ):
            platform = EntityPlatform(
                hass=hass,
                logger=logging.getLogger(__name__),
                domain=domain,
                platform_name="fabman",
                platform=None,
                scan_interval=timedelta(seconds=30),
                entity_namespace=None,
            )
            platform.config_entry = entry
            platforms[domain] = platform

            def add(entities, platform=platform):
                tasks.append(
                    hass.async_create_task(platform.async_add_entities(entities))
                )

            await module.async_setup_entry(hass, entry, add)
        await flush()

    async def reset():
        await entry._async_process_on_unload(hass)
        for platform in platforms.values():
            await platform.async_reset()
        await flush()
        platforms.clear()

    def all_entities():
        return {
            entity.unique_id: entity
            for platform in platforms.values()
            for entity in platform.entities.values()
        }

    yield SimpleNamespace(
        entry=entry,
        platforms=platforms,
        setup=setup,
        reset=reset,
        flush=flush,
        entities=all_entities,
        registry=er.async_get(hass),
        devices=dr.async_get(hass),
    )
    await reset()
    assert not list(coordinator.async_contexts())
    assert not coordinator._listeners


@pytest.mark.parametrize("state", ["active", "locked"])
async def test_new_resources_appear_once_on_all_platforms_without_reload(
    runtime, coordinator, state
):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    assert len(runtime.entities()) == 5
    coordinator.async_set_updated_data(
        {1: machine(), 2: {**machine(2), "state": state}}
    )
    await runtime.flush()
    entities = runtime.entities()
    assert len(entities) == 10
    assert len({e.registry_entry.device_id for e in entities.values()}) == 2
    coordinator.async_set_updated_data({1: machine(), 2: machine(2)})
    await runtime.flush()
    assert runtime.entities() == entities


@pytest.mark.parametrize("state", ["archived", "deleted"])
async def test_inactive_resources_survive_reload_and_reactivation_with_same_ids(
    runtime, coordinator, hass, state
):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    identities = {
        k: (v.entity_id, v.registry_entry.id, v.registry_entry.device_id)
        for k, v in runtime.entities().items()
    }
    inactive = {**machine(), "state": state}
    never_used_here = {**machine(2), "state": state}
    coordinator.async_set_updated_data({1: inactive, 2: never_used_here})
    await runtime.flush()
    assert len(runtime.entities()) == 5
    assert all(
        hass.states.get(e.entity_id).state == "unavailable"
        for e in runtime.entities().values()
    )
    assert all(
        e.extra_state_attributes["resource_state"] == state
        for e in runtime.entities().values()
        if e.extra_state_attributes is not None
    )
    target = next(
        e for e in runtime.entities().values() if isinstance(e, switch.FabmanSwitch)
    )
    with patch("custom_components.fabman.switch.async_get_clientsession") as session:
        with pytest.raises(HomeAssistantError, match="unavailable"):
            await target.async_turn_on()
        session.assert_not_called()
    await runtime.reset()
    await runtime.setup()
    assert len(runtime.entities()) == 5
    assert all(not e.available for e in runtime.entities().values())
    coordinator.async_set_updated_data({1: machine()})
    await runtime.flush()
    assert identities == {
        k: (v.entity_id, v.registry_entry.id, v.registry_entry.device_id)
        for k, v in runtime.entities().items()
    }
    assert all(e.available for e in runtime.entities().values())


async def test_renames_follow_source_and_preserve_user_names_and_entity_ids(
    runtime, coordinator, hass
):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    original = {k: e.entity_id for k, e in runtime.entities().items()}
    coordinator.async_set_updated_data({1: {**machine(), "name": "Renamed source"}})
    await runtime.flush()
    entities = runtime.entities()
    status = next(e for e in entities.values() if isinstance(e, sensor.FabmanSensor))
    device_id = status.registry_entry.device_id
    assert runtime.devices.async_get(device_id).name == "Renamed source (1)"
    assert status.name == "Renamed source Status"
    connectivity = next(
        e
        for e in entities.values()
        if isinstance(e, binary_sensor.FabmanConnectivitySensor)
    )
    assert (
        hass.states.get(connectivity.entity_id).attributes["friendly_name"]
        == "Renamed source (1) Connectivity"
    )
    runtime.devices.async_update_device(
        device_id, name_by_user="My device", area_id=None
    )
    runtime.registry.async_update_entity(status.entity_id, name="My status")
    await runtime.flush()
    coordinator.async_set_updated_data(
        {1: {**machine(), "name": "Another source name"}}
    )
    await runtime.flush()
    assert runtime.devices.async_get(device_id).name == "Another source name (1)"
    assert runtime.devices.async_get(device_id).name_by_user == "My device"
    assert runtime.registry.async_get(status.entity_id).name == "My status"
    assert hass.states.get(status.entity_id).attributes["friendly_name"] == "My status"
    assert original == {k: e.entity_id for k, e in runtime.entities().items()}


async def test_api_failure_does_not_discover_or_delete_and_recovery_adds_new(
    runtime, coordinator
):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    before = runtime.entities()
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(side_effect=FabmanAPIError("failed page")),
    ):
        await coordinator.async_refresh()
    await runtime.flush()
    assert before == runtime.entities()
    assert all(not e.available for e in before.values())
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[machine(), machine(2)]),
    ):
        await coordinator.async_refresh()
    await runtime.flush()
    assert len(runtime.entities()) == 10


@pytest.mark.parametrize(
    "state, allowed",
    [("active", False), ("locked", False), ("archived", True), ("deleted", True)],
)
async def test_manual_removal_only_for_inactive_resources(
    coordinator, hass, state, allowed
):
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[{**machine(), "state": state}]),
    ):
        await coordinator.async_refresh()
    device = SimpleNamespace(identifiers={("fabman", "fabman_resource_1")})
    assert (
        await async_remove_config_entry_device(
            hass, SimpleNamespace(entry_id="first"), device
        )
        is allowed
    )
    coordinator.async_set_update_error(UpdateFailed("outage"))
    assert not await async_remove_config_entry_device(
        hass, SimpleNamespace(entry_id="first"), device
    )


async def test_manual_removal_refused_when_missing_resource_might_be_malformed(
    coordinator, hass
):
    device = SimpleNamespace(identifiers={("fabman", "fabman_resource_1")})
    entry = SimpleNamespace(entry_id="first")
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[None, machine(2)]),
    ):
        await coordinator.async_refresh()
    assert not await async_remove_config_entry_device(hass, entry, device)
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[machine(2)]),
    ):
        await coordinator.async_refresh()
    assert await async_remove_config_entry_device(hass, entry, device)
    assert not await async_remove_config_entry_device(
        hass, entry, SimpleNamespace(identifiers={("other", "fabman_resource_1")})
    )


async def test_manually_removed_archived_device_stays_removed_until_reactivation(
    runtime, coordinator, hass
):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    device_id = next(iter(runtime.entities().values())).registry_entry.device_id
    archived = {**machine(), "state": "archived"}
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[archived]),
    ):
        await coordinator.async_refresh()
    await runtime.flush()
    assert await async_remove_config_entry_device(
        hass, runtime.entry, runtime.devices.async_get(device_id)
    )
    runtime.devices.async_remove_device(device_id)
    await runtime.flush()
    assert not runtime.entities()
    coordinator.async_set_updated_data({1: archived})
    await runtime.flush()
    assert not runtime.entities()
    coordinator.async_set_updated_data({1: machine()})
    await runtime.flush()
    assert len(runtime.entities()) == 5


async def test_archiving_drops_pending_command_and_door_timer(coordinator):
    from homeassistant.util import dt as dt_util

    resource = machine()
    resource.update(
        controlType="door",
        maxOfflineUsage=60,
        lastUsed={"at": dt_util.utcnow().isoformat()},
    )
    coordinator.async_set_updated_data({1: resource})
    handle = coordinator._door_timers[1]
    coordinator.async_note_command(1, True)
    archived = deepcopy(resource)
    archived["state"] = "archived"
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[archived]),
    ):
        await coordinator.async_refresh()
    assert handle.cancelled()
    assert not coordinator._door_timers
    assert not coordinator.pending_commands
    coordinator.async_note_command(1, True)
    assert not coordinator.pending_commands


async def test_resource_without_bridge_is_discovered_when_bridge_is_added(
    runtime, coordinator
):
    unsupported = {**machine(2), "_embedded": {}}
    coordinator.async_set_updated_data({1: machine(), 2: unsupported})
    await runtime.setup()
    assert len(runtime.entities()) == 5
    coordinator.async_set_updated_data({1: machine(), 2: machine(2)})
    await runtime.flush()
    assert len(runtime.entities()) == 10


async def test_disabled_entity_is_not_rediscovered_and_manual_cleanup_is_respected(
    runtime, coordinator
):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    entity = next(iter(runtime.entities().values()))
    entity_id = entity.entity_id
    device_id = entity.registry_entry.device_id
    runtime.registry.async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    await runtime.flush()
    runtime.registry.async_update_entity(
        entity_id, new_entity_id="binary_sensor.custom_disabled_id"
    )
    await runtime.flush()
    archived = {**machine(), "state": "archived"}
    coordinator.async_set_updated_data({1: archived})
    await runtime.flush()
    runtime.devices.async_remove_device(device_id)
    await runtime.flush()
    coordinator.async_set_updated_data({1: archived})
    await runtime.flush()
    assert not runtime.entities()
    assert not er.async_entries_for_config_entry(runtime.registry, "first")
    coordinator.async_set_updated_data({1: machine()})
    await runtime.flush()
    # HA may retain the user's disabled preference in its deleted-entry cache.
    entries = er.async_entries_for_config_entry(runtime.registry, "first")
    assert len(entries) == 5


async def test_expired_door_acknowledgement_publishes_off_in_ha(
    runtime, coordinator, hass
):
    from homeassistant.util import dt as dt_util

    original = machine(active=False)
    original.update(controlType="door", maxOfflineUsage=3)
    original["lastUsed"]["id"] = 10
    coordinator.async_set_updated_data({1: original})
    await runtime.setup()
    coordinator.async_note_command(1, True)
    entities = runtime.entities()
    door_switch = next(
        e for e in entities.values() if isinstance(e, switch.FabmanSwitch)
    )
    assert hass.states.get(door_switch.entity_id).state == "on"
    assert hass.states.get(door_switch.entity_id).attributes["assumed_state"]
    reported = deepcopy(original)
    at = (dt_util.utcnow() - timedelta(seconds=5)).isoformat()
    reported["lastUsed"].update(id=11, at=at, stoppedAt=at)
    with patch(
        "custom_components.fabman.coordinator.FabmanAPI.get_resources",
        new=AsyncMock(return_value=[reported]),
    ):
        await coordinator.async_refresh()
    await runtime.flush()
    for entity in entities.values():
        expected = (
            "unknown"
            if isinstance(entity, event.FabmanActivationEvent)
            else "on"
            if isinstance(entity, binary_sensor.FabmanConnectivitySensor)
            else "off"
        )
        assert hass.states.get(entity.entity_id).state == expected
    assert not hass.states.get(door_switch.entity_id).attributes.get(
        "assumed_state", False
    )


async def test_pos_is_read_only_and_emits_safe_authorization_events(
    runtime, coordinator, hass
):
    pos = {**machine(1515), "controlType": "pos"}
    coordinator.async_set_updated_data({1515: pos})
    await runtime.setup()

    entities = runtime.entities()
    assert len(entities) == 2
    assert {entity.platform.domain for entity in entities.values()} == {
        "binary_sensor",
        "event",
    }
    authorization = next(
        entity for entity in entities.values() if isinstance(entity, FabmanPOSEvent)
    )
    coordinator._dispatch_pos_event(
        {
            "id": 812,
            "resource": 1515,
            "type": "allowed",
            "createdAt": "2026-10-22T10:00:00+00:00",
            "member": {"emailAddress": "private@example.com"},
        }
    )
    await runtime.flush()

    state = hass.states.get(authorization.entity_id)
    assert state.state is not None
    assert state.attributes["event_type"] == "authorized"
    assert state.attributes["log_id"] == 812
    assert "member" not in state.attributes
    assert "private@example.com" not in str(state.attributes)


async def test_nuki_entities_separate_access_from_lock_and_battery_state(
    runtime, coordinator, hass
):
    nuki = {
        **machine(1523),
        "controlType": "nuki",
        "space": 5,
        "nukiDeviceId": 88,
        "maxOfflineUsage": 60,
        "lastUsed": {"at": dt_util.utcnow().isoformat()},
    }
    device = {
        "smartlockId": 88,
        "serverState": 0,
        "state": {"mode": 2, "state": 1, "batteryCharge": 80},
    }
    coordinator.async_set_updated_data({1523: nuki})
    coordinator._nuki_devices_by_space = {"5": {"88": device}}
    await runtime.setup()

    entities = runtime.entities()
    lock_sensor = next(
        entity
        for entity in entities.values()
        if isinstance(entity, FabmanNukiLockSensor)
    )
    battery = next(
        entity
        for entity in entities.values()
        if isinstance(entity, FabmanNukiBatterySensor)
    )
    activity = next(
        entity
        for entity in entities.values()
        if isinstance(entity, binary_sensor.FabmanActivitySensor)
    )
    assert len(entities) == 7
    assert lock_sensor.is_on is False
    assert battery.native_value == 80
    assert hass.states.get(activity.entity_id).state == "on"

    coordinator._nuki_devices_by_space["5"]["88"] = {
        **device,
        "serverState": 1,
    }
    await runtime.flush()
    assert lock_sensor.is_on is None
    assert battery.native_value is None
    assert lock_sensor.extra_state_attributes["status_reason"] == "nuki_offline"


async def test_check_in_terminals_share_a_space_service_without_any_controls(
    runtime, coordinator, hass
):
    coordinator.presence.spaces[SCOPE] = SpacePresence(
        *SCOPE,
        name="Synthetic space",
        available=True,
        cursor=BASE,
        baseline=BASE,
        last_successful_sync=BASE,
        sessions={10: parse_session(attendance(start=-100), 42)},
    )
    coordinator.async_set_updated_data({1370: terminal(), 1371: terminal(1371)})
    coordinator._session.post = Mock(side_effect=AssertionError("Read-only attendance"))
    await runtime.setup()
    entities = runtime.entities().values()
    assert len(entities) == 4  # Two bridge connections and one sensor/event pair.
    roster = next(e for e in entities if isinstance(e, FabmanCheckedInMembersSensor))
    activity = next(e for e in entities if isinstance(e, FabmanCheckInActivityEvent))
    assert roster.registry_entry.device_id == activity.registry_entry.device_id
    assert len({e.registry_entry.device_id for e in entities}) == 3
    assert hass.states.get(roster.entity_id).state == "1"
    assert roster.extra_state_attributes["members"][0]["member_id"] == 6
    assert not any(
        isinstance(
            e,
            (
                switch.FabmanSwitch,
                binary_sensor.FabmanActivitySensor,
                sensor.FabmanSensor,
            ),
        )
        for e in entities
    )
    transitions = []
    remove = hass.bus.async_listen(
        "state_changed", lambda event: transitions.append(event)
    )
    for event_type in ("checked_in", "checked_out"):
        coordinator.presence.dispatch(
            {
                "event_type": event_type,
                "account_id": 42,
                "space_id": 5,
                "member_id": 7,
                "member_name": "Synthetic Member 7",
                "log_id": 11,
                "resource_id": 1371,
                "occurred_at": BASE.isoformat(),
            }
        )
    await runtime.flush()
    remove()
    assert [
        e.data["new_state"].attributes["event_type"]
        for e in transitions
        if e.data["entity_id"] == activity.entity_id
    ] == ["checked_in", "checked_out"]
    assert hass.states.get(activity.entity_id).attributes["member_id"] == 7
    coordinator._session.post.assert_not_called()


async def test_old_switch_becomes_unavailable_when_resource_changes_to_check_in(
    runtime, coordinator, hass
):
    coordinator.async_set_updated_data({1370: machine(1370)})
    await runtime.setup()
    old_switch = next(
        e for e in runtime.entities().values() if isinstance(e, switch.FabmanSwitch)
    )
    coordinator.async_set_updated_data({1370: terminal()})
    await runtime.flush()
    assert hass.states.get(old_switch.entity_id).state == "unavailable"
    with patch("custom_components.fabman.switch.async_get_clientsession") as session:
        for action in (old_switch.async_turn_on, old_switch.async_turn_off):
            with pytest.raises(HomeAssistantError, match="unavailable"):
                await action()
        with pytest.raises(HomeAssistantError, match="unavailable"):
            await old_switch.async_turn_on_for_member(member_id=6)
        session.assert_not_called()


async def test_attendance_failures_only_make_the_space_entities_unavailable(
    runtime, coordinator, hass
):
    resources = [machine(), terminal()]
    with (
        patch(
            "custom_components.fabman.coordinator.FabmanAPI.get_resources",
            new=AsyncMock(return_value=resources),
        ),
        patch(
            "custom_components.fabman.coordinator.FabmanAPI.get_space",
            new=AsyncMock(
                return_value={"id": 5, "account": 42, "name": "Synthetic space"}
            ),
        ),
        patch(
            "custom_components.fabman.coordinator.FabmanAPI.get_check_in_logs",
            new=AsyncMock(return_value=[attendance(start=-100)]),
        ) as logs,
    ):
        await coordinator.async_refresh()
        await runtime.setup()
        roster = next(
            e
            for e in runtime.entities().values()
            if isinstance(e, FabmanCheckedInMembersSensor)
        )
        assert hass.states.get(roster.entity_id).state == "1"
        logs.side_effect = FabmanAPIError("HTTP 403")
        await coordinator.async_refresh()
        await runtime.flush()
    assert coordinator.last_update_success
    assert hass.states.get(roster.entity_id).state == "unavailable"
    assert len(roster.extra_state_attributes["members"]) == 1
    assert all(
        e.available
        for e in runtime.entities().values()
        if not isinstance(e, (FabmanCheckedInMembersSensor, FabmanCheckInActivityEvent))
    )


async def test_space_entities_are_discovered_dynamically_and_keep_their_ids_on_reload(
    runtime, coordinator
):
    coordinator.async_set_updated_data({1: machine()})
    await runtime.setup()
    coordinator.presence.spaces[SCOPE] = SpacePresence(
        *SCOPE,
        name="Space 5",
        available=True,
        cursor=BASE,
        baseline=BASE,
    )
    coordinator.async_set_updated_data({1: machine(), 1370: terminal()})
    await runtime.flush()
    roster = next(
        e
        for e in runtime.entities().values()
        if isinstance(e, FabmanCheckedInMembersSensor)
    )
    identities = {
        key: (e.entity_id, e.registry_entry.device_id)
        for key, e in runtime.entities().items()
    }
    device_id = roster.registry_entry.device_id
    runtime.devices.async_update_device(device_id, name_by_user="My attendance")
    coordinator.presence.spaces[SCOPE] = replace(
        coordinator.presence.spaces[SCOPE], name="Resolved space name"
    )
    coordinator.async_update_listeners()
    await runtime.flush()
    assert runtime.devices.async_get(device_id).name == "Fabman – Resolved space name"
    assert runtime.devices.async_get(device_id).name_by_user == "My attendance"
    await runtime.reset()
    await runtime.setup()
    assert identities == {
        key: (e.entity_id, e.registry_entry.device_id)
        for key, e in runtime.entities().items()
    }


async def test_space_device_cleanup_requires_an_inactive_scope_and_good_inventory(
    runtime, coordinator, hass
):
    coordinator.presence.spaces[SCOPE] = SpacePresence(*SCOPE, name="Synthetic space")
    coordinator.async_set_updated_data({1370: terminal()})
    await runtime.setup()
    roster = next(
        e
        for e in runtime.entities().values()
        if isinstance(e, FabmanCheckedInMembersSensor)
    )
    device = runtime.devices.async_get(roster.registry_entry.device_id)
    coordinator.inventory_complete = True
    assert not await async_remove_config_entry_device(hass, runtime.entry, device)
    coordinator.presence.spaces[SCOPE] = replace(
        coordinator.presence.spaces[SCOPE], active=False
    )
    coordinator.async_set_updated_data({})
    assert not await async_remove_config_entry_device(hass, runtime.entry, device)
    coordinator.inventory_complete = True
    assert await async_remove_config_entry_device(hass, runtime.entry, device)


async def test_coordinator_delivers_both_short_visit_events_after_the_roster_update(
    runtime, coordinator, hass
):
    async def logs(account_id, space_id, **kwargs):
        return [attendance(start=2, end=10)] if kwargs.get("status") == "all" else []

    with (
        patch(
            "custom_components.fabman.coordinator.FabmanAPI.get_resources",
            new=AsyncMock(return_value=[terminal()]),
        ),
        patch(
            "custom_components.fabman.coordinator.FabmanAPI.get_space",
            new=AsyncMock(
                return_value={"id": 5, "account": 42, "name": "Synthetic space"}
            ),
        ),
        patch(
            "custom_components.fabman.coordinator.FabmanAPI.get_check_in_logs",
            side_effect=logs,
        ),
        patch("custom_components.fabman.coordinator.dt_util.utcnow", return_value=BASE),
    ):
        await coordinator.async_refresh()
        await runtime.setup()
        activity = next(
            e
            for e in runtime.entities().values()
            if isinstance(e, FabmanCheckInActivityEvent)
        )
        roster = next(
            e
            for e in runtime.entities().values()
            if isinstance(e, FabmanCheckedInMembersSensor)
        )
        observed = []
        remove = hass.bus.async_listen(
            "state_changed", lambda event: observed.append(event)
        )
        with patch(
            "custom_components.fabman.coordinator.dt_util.utcnow",
            return_value=BASE + timedelta(seconds=30),
        ):
            await coordinator.async_refresh()
            await runtime.flush()
        remove()
    assert hass.states.get(roster.entity_id).state == "0"
    event_types = [
        event.data["new_state"].attributes["event_type"]
        for event in observed
        if event.data["entity_id"] == activity.entity_id
    ]
    assert sorted(event_types) == ["checked_in", "checked_out"]
