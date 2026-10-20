"""Resource state and device information helpers."""

import math
import urllib.parse
from datetime import timedelta

from homeassistant.util import dt as dt_util

from .const import DOMAIN


def get_door_close_time(resource: dict):
    """Return a valid door timeout, or None for inactive/invalid usage."""
    if resource.get("controlType") != "door":
        return None
    last_used = resource.get("lastUsed") or {}
    if not last_used or last_used.get("stopType") is not None:
        return None
    timestamp = last_used.get("at")
    if not isinstance(timestamp, str):
        return None
    try:
        started_at = dt_util.parse_datetime(timestamp)
        seconds = float(resource.get("maxOfflineUsage") or 0)
        if started_at is None or not math.isfinite(seconds) or seconds <= 0:
            return None
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=dt_util.UTC)
        return started_at + timedelta(seconds=seconds)
    except (TypeError, ValueError, OverflowError):
        return None


def resource_is_on(resource: dict) -> bool:
    """Use the same status rules for sensors and switches."""
    last_used = resource.get("lastUsed") or {}
    if not last_used or last_used.get("stopType") is not None:
        return False
    if resource.get("controlType") == "door":
        close_time = get_door_close_time(resource)
        return close_time is not None and dt_util.utcnow() < close_time
    return True


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
