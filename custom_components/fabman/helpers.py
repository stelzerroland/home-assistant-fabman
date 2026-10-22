"""Resource state and device information helpers."""

import urllib.parse

from .activity import door_release_deadline, evaluate_activity
from .const import DOMAIN


def get_door_close_time(resource: dict):
    """Return the end of a reported door release, not a physical contact state."""
    return door_release_deadline(resource)


def resource_is_on(resource: dict) -> bool | None:
    """Return API-reported activity, including an explicitly unknown result."""
    return evaluate_activity(resource).is_on


def is_supported_resource(resource):
    """Keep malformed bridge metadata local to the affected resource."""
    if not isinstance(resource, dict):
        return False
    embedded = resource.get("_embedded")
    return (
        resource.get("controlType") in ("machine", "door", "pos", "nuki")
        and isinstance(embedded, dict)
        and isinstance(embedded.get("bridge"), dict)
        and bool(embedded["bridge"])
    )


def get_base_url(api_url: str) -> str:
    """
    Extrahiert den Basis-URL (Schema + Host) aus der API-URL.
    Beispiel: aus 'https://internal.fabman.io/api/v1' wird 'https://internal.fabman.io'
    """
    parsed = urllib.parse.urlparse(api_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def get_device_info(resource: dict, api_url: str) -> dict:
    """
    Erzeugt ein device_info-Dictionary für eine Fabman-Ressource.
    Erwartet, dass resource eine 'id' und eine 'account'-Angabe enthält.
    Baut die configuration_url wie folgt:
      {base_url}/manage/{account_id}/configuration/resources/{resource_id}
    """
    resource_id = resource.get("id")
    account_id = resource.get("account")
    base_url = get_base_url(api_url)
    configuration_url = (
        f"{base_url}/manage/{account_id}/configuration/resources/{resource_id}"
    )

    return {
        "identifiers": {(DOMAIN, f"fabman_resource_{resource_id}")},
        "name": f"{resource.get('name', 'Resource')} ({resource_id})",
        "manufacturer": "Fabman",
        "model": resource.get("controlType", "Unknown"),
        "configuration_url": configuration_url,
    }
