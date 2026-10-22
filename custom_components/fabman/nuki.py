"""Interpret Nuki device data returned through Fabman."""


def normalized_identifier(value):
    """Normalize the numeric identifiers used by Fabman and Nuki."""
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip():
        value = value.strip()
        if len(value) <= 20 and value.isdecimal() and int(value) > 0:
            return str(int(value))
        return value
    return None


def device_identifier(device):
    """Return a stable device ID from the documented response variants."""
    if not isinstance(device, dict):
        return None
    for key in ("smartlockId", "nukiDeviceId", "deviceId", "id"):
        identifier = normalized_identifier(device.get(key))
        if identifier is not None:
            return identifier
    return None


def is_unlocked(device):
    """Return HA lock binary-sensor state: True unlocked, False locked."""
    if not isinstance(device, dict):
        return None
    device_type = device.get("type")
    if type(device_type) is int and device_type not in (0, 3, 4, 5):
        # Nuki Openers and Boxes use different state meanings; 1 is not locked.
        return None
    server_state = device.get("serverState")
    if type(server_state) is int and server_state != 0:
        return None
    state = device.get("state")
    if not isinstance(state, dict):
        return None
    value = state.get("state")
    if type(value) is not int:
        return None
    if value == 1:
        return False
    if value in (3, 5, 6):
        return True
    return None


def battery_level(device):
    """Return a valid Nuki battery percentage, if present."""
    if not isinstance(device, dict):
        return None
    server_state = device.get("serverState")
    if type(server_state) is int and server_state != 0:
        return None
    state = device.get("state")
    if not isinstance(state, dict):
        return None
    value = state.get("batteryCharge")
    if type(value) is not int or not 0 <= value <= 100:
        return None
    return value
