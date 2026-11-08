"""Authenticated HA WebSocket gateway; never accepts a caller-supplied identity."""

import probatio
from homeassistant.components import websocket_api

from .const import DATA_DIRECT_LINKS
from .direct_links import DirectLinkError


@websocket_api.websocket_command(
    {
        "type": "fabman/direct_link/prepare",
        probatio.Required("entry_id"): probatio.All(
            str, probatio.Length(min=1, max=128)
        ),
        probatio.Required("resource_id"): probatio.All(
            int, probatio.Range(min=1, max=2147483647)
        ),
    }
)
@websocket_api.async_response
async def prepare(hass, connection, msg):
    try:
        result = await hass.data[DATA_DIRECT_LINKS].prepare(
            connection.user,
            msg["entry_id"],
            msg["resource_id"],
            connection.context(msg),
        )
    except DirectLinkError as err:
        connection.send_error(msg["id"], err.code, err.code)
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        "type": "fabman/direct_link/execute",
        probatio.Required("confirmation_id"): probatio.All(
            str, probatio.Length(min=1, max=128)
        ),
    }
)
@websocket_api.async_response
async def execute(hass, connection, msg):
    try:
        result = hass.data[DATA_DIRECT_LINKS].execute(
            connection.user, msg["confirmation_id"]
        )
    except DirectLinkError as err:
        connection.send_error(msg["id"], err.code, err.code)
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        "type": "fabman/direct_link/status",
        probatio.Required("operation_id"): probatio.All(
            str, probatio.Length(min=1, max=128)
        ),
    }
)
@websocket_api.async_response
async def status(hass, connection, msg):
    try:
        result = hass.data[DATA_DIRECT_LINKS].status(
            connection.user, msg["operation_id"]
        )
    except DirectLinkError as err:
        connection.send_error(msg["id"], err.code, err.code)
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command({"type": "fabman/direct_link/list"})
@websocket_api.async_response
async def list_links(hass, connection, msg):
    try:
        result = hass.data[DATA_DIRECT_LINKS].list_links(connection.user)
    except DirectLinkError as err:
        connection.send_error(msg["id"], err.code, err.code)
    else:
        connection.send_result(msg["id"], result)


def async_register(hass):
    for handler in (prepare, execute, status, list_links):
        websocket_api.async_register_command(hass, handler)
