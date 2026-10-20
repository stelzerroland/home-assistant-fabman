# v0.2.0b1 (beta)

- Add native binary activity sensors while preserving existing device and entity identities.
- Represent ambiguous usage as unknown and accepted commands as assumed switch states.
- End door release locally at the grant timestamp plus maxOfflineUsage, without a server off event.
- Validate complete paginated snapshots and protect newer state from outdated reads.
- Validate with 138 tests on Home Assistant 2026.10.1 and 2026.10.2.

This prerelease changes existing status behavior and is intended for passive testing.
See [installation, behavior changes and rollback](docs/releases/v0.2.0b1.md).

# v0.1.1

This release fixes resource status updates, bridge command errors and webhook
handling for existing Fabman installations.

## Fixes

- Failed bridge commands now report an error to Home Assistant and automations.
- Sensors safely handle resources with no previous usage (`lastUsed: null`).
- Successful bridge commands update switches and status sensors together.
- Door status includes a valid usage timestamp and updates when its timeout
  expires, including when periodic polling is disabled.
- Removed resources become unavailable instead of appearing switched off.
- Each configuration has its own webhook URL. The existing
  `/api/webhook/fabman_webhook` URL remains supported and refreshes all configured
  Fabman connections.
- Pending door and command timers are cancelled when the configuration unloads.
- Test events and invalid webhook payloads are handled without server errors.
- Default API URL and polling settings are applied consistently.
- Text status sensors no longer advertise numeric power measurement metadata.

## Updating

Install the update through HACS and restart Home Assistant. Existing configuration,
entity unique IDs and the existing webhook URL are preserved. No reconfiguration
is required.

Manual installations must replace `custom_components/fabman/` with the folder from
this release and restart Home Assistant.

## Validation

34 regression tests pass against Home Assistant 2026.10.2 using simulated API
responses. Real Fabman hardware has not been exercised as part of these tests.
The integration remains an alpha release.
