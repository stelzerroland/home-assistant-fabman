"""Fabman API client."""
import logging
from urllib.parse import urljoin
import json

_LOGGER = logging.getLogger(__name__)

class FabmanAPI:
    def __init__(self, session, base_url, api_key):
        # Entferne einen eventuellen Trailing Slash
        self._session = session
        self._base_url = base_url.rstrip("/")
        # Jetzt wird der API-Key als Bearer-Token übergeben:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def get_resources(self):
        """Rufe alle Ressourcen (mit Pagination) ab."""
        resources = []
        url = f"{self._base_url}/resources?limit=50&embed=bridge"

        while url:
            _LOGGER.debug("Abfrage Fabman API: %s", url)
            async with self._session.get(url, headers=self._headers) as response:
                if response.status != 200:
                    text = await response.text()
                    _LOGGER.error("Fehler beim Abruf von %s: %s - %s", url, response.status, text)
                    raise Exception(f"Error fetching resources: {response.status}")

                data = await response.json()
                resources.extend(data)

                # Pagination: Prüfe den Link-Header nach einem "next"-Link
                link_header = response.headers.get("Link")
                next_url = None
                if link_header:
                    parts = link_header.split(",")
                    for part in parts:
                        if 'rel="next"' in part:
                            start = part.find("<") + 1
                            end = part.find(">")
                            next_url = part[start:end]
                            break

                # Falls der next_url relativ ist, in einen absoluten URL umwandeln:
                if next_url and not next_url.startswith("http"):
                    next_url = urljoin(self._base_url, next_url)
                    
                url = next_url

        return resources


