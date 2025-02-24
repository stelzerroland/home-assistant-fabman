"""Fabman API client mit Pagination."""
import logging
from urllib.parse import urljoin

_LOGGER = logging.getLogger(__name__)

class FabmanAPI:
    def __init__(self, session, base_url, api_key):
        # Entferne einen eventuellen Trailing Slash
        self._session = session
        self._base_url = base_url.rstrip("/")
        # Der API-Key wird als Bearer-Token übergeben:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @property
    def base_url(self):
        """Gibt den Basis-URL zurück."""
        return self._base_url
    
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

                # Falls next_url relativ ist, umwandeln in absolute URL:
                if next_url and not next_url.startswith("http"):
                    next_url = urljoin(self._base_url, next_url)
                    
                url = next_url

        return resources
