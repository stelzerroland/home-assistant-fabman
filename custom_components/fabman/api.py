"""Read complete Fabman resource snapshots without exposing response bodies."""

import math
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import aiohttp


class FabmanAPIError(Exception):
    """A resource snapshot could not be retrieved or validated."""


class FabmanAuthenticationError(FabmanAPIError):
    """The API rejected the credentials or resource access."""


class FabmanRateLimitError(FabmanAPIError):
    """The API asked the client to slow down."""

    def __init__(self, retry_after):
        super().__init__("Fabman request rate limit reached")
        self.retry_after = retry_after


class FabmanAPI:
    """Fetch all pages before publishing any part of a resource list."""

    def __init__(self, session, base_url, api_key):
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @property
    def base_url(self):
        return self._base_url

    async def get_resources(self):
        resources = []
        states = ("active", "locked", "archived", "deleted")
        url = f"{self._base_url}/resources?limit=50&embed=bridge&{urlencode([('state', state) for state in states])}"
        origin = urlsplit(url)
        visited = set()
        expected_count = None
        try:
            while url:
                target = urlsplit(url)
                if (
                    (target.scheme, target.hostname, target.port)
                    != (origin.scheme, origin.hostname, origin.port)
                    or target.username is not None
                    or target.password is not None
                    or target.path != origin.path
                    or target.fragment
                    or url in visited
                ):
                    raise FabmanAPIError("Invalid or repeated resource pagination link")
                visited.add(url)
                async with self._session.get(
                    url,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=False,
                ) as response:
                    if response.status in (401, 403):
                        raise FabmanAuthenticationError("Fabman resource access denied")
                    if response.status == 429:
                        try:
                            delay = float(response.headers.get("Retry-After", 2))
                            if not math.isfinite(delay):
                                delay = 2
                        except (TypeError, ValueError):
                            delay = 2
                        raise FabmanRateLimitError(max(2, delay))
                    if response.status != 200:
                        raise FabmanAPIError(
                            f"Fabman resource request failed: HTTP {response.status}"
                        )
                    data = await response.json()
                    if not isinstance(data, list):
                        raise FabmanAPIError("Fabman resource response is not a list")
                    resources.extend(data)

                    count = response.headers.get("X-Total-Count")
                    if count is not None:
                        try:
                            count = int(count)
                        except (TypeError, ValueError):
                            raise FabmanAPIError("Invalid resource count") from None
                        if count < 0 or (
                            expected_count is not None and count != expected_count
                        ):
                            raise FabmanAPIError("Inconsistent resource count")
                        expected_count = count
                    next_link = response.links.get("next")
                    url = urljoin(url, str(next_link["url"])) if next_link else None
                    if url:
                        parts = urlsplit(url)
                        query = parse_qsl(parts.query, keep_blank_values=True)
                        next_states = [value for key, value in query if key == "state"]
                        if next_states and (
                            len(next_states) != len(states)
                            or set(next_states) != set(states)
                        ):
                            raise FabmanAPIError(
                                "Inconsistent resource pagination filters"
                            )
                        if not next_states:
                            query.extend(("state", state) for state in states)
                        if not any(key == "embed" for key, value in query):
                            query.append(("embed", "bridge"))
                        url = urlunsplit(parts._replace(query=urlencode(query)))
            if expected_count is not None and expected_count != len(resources):
                raise FabmanAPIError("Incomplete resource snapshot")
        except (aiohttp.ClientError, TimeoutError, ValueError):
            # Transport/JSON exceptions can contain URLs, credentials or bodies.
            raise FabmanAPIError("Fabman resource request or response failed") from None
        return resources

    async def get_resource_logs(self, resource_id, from_time):
        """Read the POS authorization logs created since the given timestamp."""
        if type(resource_id) is not int or resource_id <= 0:
            raise FabmanAPIError("Invalid Fabman resource ID")
        if not isinstance(from_time, str) or not from_time:
            raise FabmanAPIError("Invalid Fabman log timestamp")
        return await self._get_collection(
            "resource-logs",
            {
                "resource": resource_id,
                "from": from_time,
                "type": "allowed",
                "limit": 100,
            },
        )

    async def get_nuki_devices(self, space_id):
        """Read the Nuki state already synchronized by Fabman for one space."""
        if type(space_id) is int and space_id > 0:
            space_id = str(space_id)
        elif (
            not isinstance(space_id, str)
            or not space_id.isdecimal()
            or len(space_id) > 20
            or int(space_id) <= 0
        ):
            raise FabmanAPIError("Invalid Fabman space ID")
        else:
            space_id = str(int(space_id))
        return await self._get_collection(
            f"spaces/{space_id}/integrations/nuki/devices", {}
        )

    async def _get_collection(self, endpoint, params):
        """Fetch a paginated list while preserving its filters and origin."""
        query_string = urlencode(params)
        url = f"{self._base_url}/{endpoint}"
        if query_string:
            url = f"{url}?{query_string}"
        origin = urlsplit(url)
        visited = set()
        expected_count = None
        items = []
        try:
            while url:
                target = urlsplit(url)
                if (
                    (target.scheme, target.hostname, target.port)
                    != (origin.scheme, origin.hostname, origin.port)
                    or target.username is not None
                    or target.password is not None
                    or target.path != origin.path
                    or target.fragment
                    or url in visited
                ):
                    raise FabmanAPIError("Invalid or repeated Fabman pagination link")
                visited.add(url)
                async with self._session.get(
                    url,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=False,
                ) as response:
                    if response.status in (401, 403):
                        raise FabmanAuthenticationError("Fabman resource access denied")
                    if response.status == 429:
                        try:
                            delay = float(response.headers.get("Retry-After", 2))
                            if not math.isfinite(delay):
                                delay = 2
                        except (TypeError, ValueError):
                            delay = 2
                        raise FabmanRateLimitError(max(2, delay))
                    if response.status != 200:
                        raise FabmanAPIError(
                            f"Fabman {endpoint} request failed: HTTP {response.status}"
                        )
                    data = await response.json()
                    if not isinstance(data, list):
                        raise FabmanAPIError("Fabman collection response is not a list")
                    items.extend(data)
                    count = response.headers.get("X-Total-Count")
                    if count is not None:
                        try:
                            count = int(count)
                        except (TypeError, ValueError):
                            raise FabmanAPIError("Invalid Fabman collection count") from None
                        if count < 0 or (
                            expected_count is not None and count != expected_count
                        ):
                            raise FabmanAPIError("Inconsistent Fabman collection count")
                        expected_count = count
                    next_link = response.links.get("next")
                    url = urljoin(url, str(next_link["url"])) if next_link else None
                    if url:
                        parts = urlsplit(url)
                        query = parse_qsl(parts.query, keep_blank_values=True)
                        for key, value in params.items():
                            expected = str(value)
                            existing = [
                                current for current_key, current in query
                                if current_key == key
                            ]
                            if existing and any(
                                current != expected for current in existing
                            ):
                                raise FabmanAPIError(
                                    "Inconsistent Fabman pagination filters"
                                )
                            if not existing:
                                query.append((key, expected))
                        url = urlunsplit(parts._replace(query=urlencode(query)))
            if expected_count is not None and expected_count != len(items):
                raise FabmanAPIError("Incomplete Fabman collection")
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise FabmanAPIError("Fabman collection request or response failed") from None
        return items
