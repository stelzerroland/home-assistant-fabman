"""Read complete Fabman resource snapshots without exposing response bodies."""

import math
from urllib.parse import urljoin, urlsplit

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
        url = f"{self._base_url}/resources?limit=50&embed=bridge"
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
            if expected_count is not None and expected_count != len(resources):
                raise FabmanAPIError("Incomplete resource snapshot")
        except (aiohttp.ClientError, TimeoutError, ValueError):
            # Transport/JSON exceptions can contain URLs, credentials or bodies.
            raise FabmanAPIError("Fabman resource request or response failed") from None
        return resources
