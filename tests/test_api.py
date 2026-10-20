"""HTTP-level tests with a local fake API; no Fabman account is contacted."""

from contextlib import asynccontextmanager
from unittest.mock import Mock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.fabman.api import (
    FabmanAPI,
    FabmanAPIError,
    FabmanAuthenticationError,
    FabmanRateLimitError,
)

from .factories import machine


@asynccontextmanager
async def fake_api(handler):
    app = web.Application()
    app.router.add_route("*", "/api/v1/resources", handler)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        yield FabmanAPI(session, str(server.make_url("/api/v1")), "synthetic-token")


async def test_85_resources_follow_query_relative_next_link():
    pages = []

    async def handler(request):
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        offset = int(request.query.get("offset", 0))
        pages.append(offset)
        headers = {"X-Total-Count": "85"}
        if offset == 0:
            headers["Link"] = '<?offset=50&limit=50&embed=bridge>; rel="next"'
        return web.json_response(
            [machine(i) for i in range(offset + 1, min(offset + 50, 85) + 1)],
            headers=headers,
        )

    async with fake_api(handler) as api:
        resources = await api.get_resources()
    assert pages == [0, 50]
    assert [resource["id"] for resource in resources] == list(range(1, 86))


async def test_empty_last_page_is_supported():
    async def handler(request):
        if "offset" in request.query:
            return web.json_response([])
        return web.json_response(
            [machine()], headers={"Link": '<?offset=1>; rel="next"'}
        )

    async with fake_api(handler) as api:
        assert len(await api.get_resources()) == 1


async def test_second_page_failure_never_returns_partial_list():
    async def handler(request):
        if "offset" in request.query:
            return web.Response(status=500, text="secret body must not be logged")
        return web.json_response(
            [machine()], headers={"Link": '<?offset=1>; rel="next"'}
        )

    async with fake_api(handler) as api:
        with pytest.raises(FabmanAPIError, match="HTTP 500") as error:
            await api.get_resources()
    assert "secret" not in str(error.value)


async def test_later_page_failure_preserves_previous_snapshot_and_marks_unavailable(
    coordinator,
):
    fail_second_page = False

    async def handler(request):
        offset = int(request.query.get("offset", 0))
        if offset and fail_second_page:
            return web.Response(status=503)
        headers = {"X-Total-Count": "85"}
        if not offset:
            headers["Link"] = '<?offset=50>; rel="next"'
        return web.json_response(
            [machine(i) for i in range(offset + 1, min(offset + 50, 85) + 1)],
            headers=headers,
        )

    async with fake_api(handler) as api:
        coordinator._session = api._session
        coordinator.api_url = api.base_url
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert len(coordinator.data) == 85
        previous_success = coordinator.last_successful_fetch
        fail_second_page = True
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert len(coordinator.data) == 85
    assert coordinator.last_successful_fetch == previous_success


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_http_failures_are_typed_and_do_not_include_confidential_body(
    status, caplog
):
    async def handler(request):
        return web.Response(
            status=status,
            text="private-member synthetic-token",
            headers={"Retry-After": "5"},
        )

    error_type = FabmanAuthenticationError if status in (401, 403) else FabmanAPIError
    async with fake_api(handler) as api:
        with pytest.raises(error_type) as error:
            await api.get_resources()
    if status == 429:
        assert isinstance(error.value, FabmanRateLimitError)
        assert error.value.retry_after == 5
    assert "private-member" not in str(error.value)
    assert "synthetic-token" not in str(error.value)
    assert "private-member" not in caplog.text


@pytest.mark.parametrize("payload", [{"error": "not a list"}, None, "invalid", 123])
async def test_json_top_level_must_be_a_list(payload):
    async def handler(request):
        return web.json_response(payload)

    async with fake_api(handler) as api:
        with pytest.raises(FabmanAPIError, match="not a list"):
            await api.get_resources()


async def test_malformed_json_is_sanitized():
    async def handler(request):
        return web.Response(text='{"private-member":', content_type="application/json")

    async with fake_api(handler) as api:
        with pytest.raises(FabmanAPIError) as error:
            await api.get_resources()
    assert "private-member" not in str(error.value)


@pytest.mark.parametrize(
    "error",
    [TimeoutError("private-token"), aiohttp.ClientConnectionError("private-token")],
)
async def test_transport_failures_are_sanitized(error):
    session = Mock(get=Mock(side_effect=error))
    api = FabmanAPI(session, "https://example.invalid/api/v1", "synthetic-token")
    with pytest.raises(FabmanAPIError) as result:
        await api.get_resources()
    assert "private-token" not in str(result.value)


@pytest.mark.parametrize(
    "link",
    [
        '<https://example.invalid/resources>; rel="next"',
        '</api/v1/members>; rel="next"',
        '<?limit=50&embed=bridge>; rel="next"',
    ],
)
async def test_invalid_or_cyclic_next_links_fail_closed(link):
    async def handler(request):
        return web.json_response([machine()], headers={"Link": link})

    async with fake_api(handler) as api:
        with pytest.raises(FabmanAPIError, match="pagination"):
            await api.get_resources()


async def test_missing_page_is_detected_when_total_count_is_available():
    async def handler(request):
        return web.json_response([machine()], headers={"X-Total-Count": "85"})

    async with fake_api(handler) as api:
        with pytest.raises(FabmanAPIError, match="Incomplete"):
            await api.get_resources()
