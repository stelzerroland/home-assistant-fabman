"""Conservative interpretation of API-reported usage, separate from commands.

This is not a physical power measurement or a door contact. See
docs/activity-contract.md for evidence, supported cases and pilot restrictions.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

SOURCE = "fabman_last_used"
STOPPED_TYPES = frozenset({"normal", "automatic", "filter", "permission"})
AMBIGUOUS_STOP_TYPES = frozenset({"offline", "takeover", "race"})


@dataclass(frozen=True)
class Activity:
    """A tri-state result with a non-personal, machine-readable explanation."""

    is_on: bool | None
    reason: str
    source: str = SOURCE


def _timestamp(value, now):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt_util.parse_datetime(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed is None or parsed.tzinfo is None or parsed > now:
        return None
    return parsed


def door_release_deadline(resource, *, now: datetime | None = None):
    """Derive the release deadline from a reported grant, never from polling time."""
    now = now or dt_util.utcnow()
    if not isinstance(resource, dict) or resource.get("controlType") != "door":
        return None
    usage = resource.get("lastUsed")
    if not isinstance(usage, dict):
        return None
    started = _timestamp(usage.get("at"), now)
    duration = resource.get("maxOfflineUsage")
    if started is None or isinstance(duration, bool):
        return None
    try:
        seconds = float(duration)
        if not math.isfinite(seconds) or seconds <= 0:
            return None
        return started + timedelta(seconds=seconds)
    except (TypeError, ValueError, OverflowError):
        return None


def evaluate_activity(resource, *, now: datetime | None = None) -> Activity:
    """Require explicit, consistent session data; never invent an off state."""
    now = now or dt_util.utcnow()
    if not isinstance(resource, dict):
        return Activity(None, "invalid_resource")
    control_type = resource.get("controlType")
    if control_type not in ("machine", "door"):
        return Activity(None, "unsupported_resource_type")
    embedded = resource.get("_embedded")
    if not isinstance(embedded, dict) or not isinstance(embedded.get("bridge"), dict):
        return Activity(None, "bridge_data_missing")
    if not embedded["bridge"]:
        return Activity(None, "bridge_data_missing")
    if "lastUsed" not in resource:
        return Activity(None, "usage_missing")
    usage = resource["lastUsed"]
    if usage is None:
        # The public response schema does not establish that null proves never-used.
        return Activity(None, "null_usage_unverified")
    if not isinstance(usage, dict) or not usage:
        return Activity(None, "invalid_usage")
    if control_type == "door":
        deadline = door_release_deadline(resource, now=now)
        if deadline is None:
            return Activity(None, "invalid_door_release_window", "door_release_timer")
        # Door usage can already be closed server-side while its output is active.
        active = now < deadline
        return Activity(
            active,
            "door_release_active" if active else "door_release_expired",
            "door_release_timer",
        )
    if "stopType" not in usage:
        return Activity(None, "stop_type_missing")
    stop_type = usage["stopType"]
    if stop_type is not None and not isinstance(stop_type, str):
        return Activity(None, "invalid_stop_type")
    if stop_type in AMBIGUOUS_STOP_TYPES:
        return Activity(None, f"ambiguous_stop_{stop_type}")
    if stop_type is not None and stop_type not in STOPPED_TYPES:
        return Activity(None, "unknown_stop_type")
    reported_at = _timestamp(usage.get("at"), now)
    if reported_at is None:
        return Activity(None, "invalid_usage_timestamp")
    stopped_at = usage.get("stoppedAt")
    if stop_type is None:
        if stopped_at is not None:
            return Activity(None, "inconsistent_usage")
        return Activity(True, "usage_active")
    stopped = _timestamp(stopped_at, now)
    # Resource lastUsed.at reflects log updates, not necessarily usage start.
    # In observed API responses it equals the log's updatedAt, including updates
    # made hours after stoppedAt. Do not compare it to the stop as a start time.
    if stopped is None:
        return Activity(None, "invalid_stop_timestamp")
    return Activity(False, "usage_stopped")
