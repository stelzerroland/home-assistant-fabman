"""Synthetic identities/dates with usage shapes checked against read-only API data."""


def machine(resource_id=1, *, active=True):
    return {
        "id": resource_id,
        "account": 42,
        "name": f"Synthetic machine {resource_id}",
        "controlType": "machine",
        "_embedded": {"bridge": {"id": resource_id + 1000, "offline": False}},
        "lastUsed": {
            "at": (
                "2020-01-01T10:00:00+00:00"
                if active
                else "2020-01-01T11:00:00.002+00:00"
            ),
            "type": "allowed",
            "stopType": None if active else "normal",
            "stoppedAt": None if active else "2020-01-01T11:00:00+00:00",
        },
    }
