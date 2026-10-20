"""Run regression tests against real Home Assistant classes."""

import sys
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame

from custom_components.fabman.const import CONF_API_TOKEN, DOMAIN
from custom_components.fabman.coordinator import FabmanDataUpdateCoordinator


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    frame.async_setup(instance)
    instance.config_entries = Mock(
        async_forward_entry_setups=AsyncMock(),
        async_unload_platforms=AsyncMock(return_value=True),
    )
    # HA's integration frame detector only recognizes POSIX source paths.
    with (
        patch("homeassistant.helpers.frame.report_usage")
        if sys.platform == "win32"
        else nullcontext()
    ):
        yield instance
    await instance.async_stop(force=True)


@pytest.fixture
async def coordinator(hass):
    with patch(
        "custom_components.fabman.coordinator.async_get_clientsession",
        return_value=Mock(),
    ):
        instance = FabmanDataUpdateCoordinator(
            hass, {CONF_API_TOKEN: "test-token", "enable_periodic_sync": False}
        )
    instance.data = {
        1: {
            "id": 1,
            "account": 42,
            "name": "Test resource",
            "controlType": "machine",
            "maxOfflineUsage": 10,
            "lastUsed": None,
            "_embedded": {"bridge": {"id": 2, "offline": False}},
        }
    }
    hass.data[DOMAIN] = {"first": instance}
    yield instance
    instance.async_cancel_pending_updates()
    await instance.async_shutdown()
