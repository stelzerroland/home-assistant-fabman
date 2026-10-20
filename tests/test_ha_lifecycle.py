"""Exercise real HA entity platforms, registries and published state changes."""

import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.fabman.binary_sensor import FabmanActivitySensor
from custom_components.fabman.sensor import FabmanSensor
from custom_components.fabman.switch import FabmanSwitch

from .factories import machine


async def test_real_registry_grouping_and_states_survive_errors_and_reload(
    hass, coordinator
):
    dr.async_setup(hass)
    await dr.async_load(hass, load_empty=True)
    await er.async_load(hass, load_empty=True)
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain="fabman",
        entry_id="first",
        title="Synthetic Fabman",
        source="user",
        data={},
        options={},
        unique_id=None,
        discovery_keys={},
        subentries_data=None,
    )
    hass.config_entries.async_get_entry.return_value = entry
    coordinator.async_set_updated_data({1: machine()})
    platforms = {}
    for domain in ("binary_sensor", "sensor", "switch"):
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
    binary = FabmanActivitySensor(coordinator, 1, "first")
    sensor = FabmanSensor(coordinator, 1, "Synthetic machine 1", "machine", 10)
    switch = FabmanSwitch(coordinator, 1, "machine")
    try:
        for domain, entity in (
            ("binary_sensor", binary),
            ("sensor", sensor),
            ("switch", switch),
        ):
            await platforms[domain].async_add_entities([entity])
            assert entity.entity_id in platforms[domain].entities
        registry = er.async_get(hass)
        entries = [
            registry.async_get(entity.entity_id) for entity in (binary, sensor, switch)
        ]
        assert all(item is not None for item in entries)
        assert len({item.device_id for item in entries}) == 1
        assert entries[0].device_id is not None
        assert entries[0].domain == "binary_sensor"
        assert hass.states.get(binary.entity_id).state == "on"

        coordinator.async_set_update_error(UpdateFailed("Simulated outage"))
        assert hass.states.get(binary.entity_id).state == "unavailable"
        coordinator.async_set_updated_data({1: machine()})
        assert hass.states.get(binary.entity_id).state == "on"
        coordinator.async_set_updated_data({1: {**machine(), "lastUsed": {}}})
        assert hass.states.get(binary.entity_id).state == "unknown"
        assert hass.states.get(sensor.entity_id).state == "unknown"
        coordinator.async_set_updated_data({})
        assert hass.states.get(binary.entity_id).state == "unavailable"
        coordinator.async_set_updated_data({1: machine()})
        assert hass.states.get(binary.entity_id).state == "on"

        coordinator.async_note_command(1, False)
        assert hass.states.get(binary.entity_id).state == "unknown"
        assumed = hass.states.get(switch.entity_id)
        assert assumed.state == "off"
        assert assumed.attributes["assumed_state"] is True
        original_entity_id = binary.entity_id
        original_registry_id = entries[0].id
        await platforms["binary_sensor"].async_reset()
        replacement = FabmanActivitySensor(coordinator, 1, "first")
        await platforms["binary_sensor"].async_add_entities([replacement])
        assert replacement.entity_id == original_entity_id
        assert registry.async_get(replacement.entity_id).id == original_registry_id
    finally:
        for platform in platforms.values():
            await platform.async_reset()
    assert not list(coordinator.async_contexts())


async def test_door_timer_publishes_native_on_then_off_in_ha(hass, coordinator):
    dr.async_setup(hass)
    await dr.async_load(hass, load_empty=True)
    await er.async_load(hass, load_empty=True)
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain="fabman",
        entry_id="first",
        title="Synthetic Fabman",
        source="user",
        data={},
        options={},
        unique_id=None,
        discovery_keys={},
        subentries_data=None,
    )
    hass.config_entries.async_get_entry.return_value = entry
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain="binary_sensor",
        platform_name="fabman",
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    resource = machine(active=False)
    resource.update(
        controlType="door",
        maxOfflineUsage=0.2,
        lastUsed={"at": dt_util.utcnow().isoformat(), "stopType": "normal"},
    )
    coordinator.async_set_updated_data({1: resource})
    coordinator.async_request_refresh = AsyncMock()
    entity = FabmanActivitySensor(coordinator, 1, "first")
    try:
        await platform.async_add_entities([entity])
        state = hass.states.get(entity.entity_id)
        assert state.state == "on"
        assert state.attributes["status_source"] == "door_release_timer"
        assert "device_class" not in state.attributes
        await asyncio.sleep(0.25)
        assert hass.states.get(entity.entity_id).state == "off"
        assert coordinator.update_interval is None
        coordinator.async_request_refresh.assert_not_awaited()
    finally:
        await platform.async_reset()
