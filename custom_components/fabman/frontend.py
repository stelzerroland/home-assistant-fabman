"""Register one bundled panel and static route for every Fabman config entry."""

import asyncio
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import DATA_DIRECT_LINKS
from .direct_links import DirectLinks
from .websocket import async_register

DATA_SETUP_LOCK = "fabman_panel_setup_lock"


async def async_setup_panel(hass, entry):
    lock = hass.data.setdefault(DATA_SETUP_LOCK, asyncio.Lock())
    async with lock:
        manager = hass.data.get(DATA_DIRECT_LINKS)
        if manager is None:
            manager = hass.data[DATA_DIRECT_LINKS] = DirectLinks(hass)
            async_register(hass)
        if not manager.static_registered:
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        "/fabman_static", str(Path(__file__).parent / "frontend"), False
                    )
                ]
            )
            manager.static_registered = True
        if not manager.panel_registered:
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path="fabman",
                webcomponent_name="fabman-panel",
                sidebar_title="Fabman",
                sidebar_icon="mdi:qrcode-scan",
                module_url="/fabman_static/fabman-panel.js?v=0.4.0b4",
                require_admin=False,
            )
            manager.panel_registered = True
        manager.attach(entry)


def async_unload_panel(hass, entry_id):
    manager = hass.data.get(DATA_DIRECT_LINKS)
    if manager is None:
        return
    manager.detach(entry_id)
    if not manager.entries and manager.panel_registered:
        frontend.async_remove_panel(hass, "fabman", warn_if_unknown=False)
        manager.panel_registered = False
