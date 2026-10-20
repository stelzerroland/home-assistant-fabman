"""Interpret Fabman's explicit bridge offline flag without coercing missing data."""


def bridge_is_connected(resource) -> bool | None:
    """Return server-reported connectivity, never inferred from API success or age."""
    if not isinstance(resource, dict):
        return None
    embedded = resource.get("_embedded")
    if not isinstance(embedded, dict):
        return None
    bridge = embedded.get("bridge")
    if not isinstance(bridge, dict):
        return None
    offline = bridge.get("offline")
    if type(offline) is not bool:
        return None
    return not offline
