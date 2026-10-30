# Unreleased

# v0.3.0b4 (beta)

- Fix email-based Home Assistant user mappings by filtering Fabman's full-text member search for a unique exact email.

See [v0.3.0b4 beta notes](docs/releases/v0.3.0b4.md).

# v0.3.0b3 (beta)

- Add read-only check-in attendance from complete active-session snapshots, with a
  space-level roster and check-in/check-out activity events.
- Add optional Home Assistant user to Fabman member mappings in the integration
  options; accept a member ID or exact email and store the resolved member ID.
- Attribute activations from mapped users to their configured Fabman member; leave
  unmapped and context-free activations with the API-key member by default.
- Add per-resource activation events and latest-actor sensor attributes, including
  assignment outcome.
- Carry the bounded command-confirmation timeout behavior from v0.3.0b2.

See [v0.3.0b3 beta notes](docs/releases/v0.3.0b3.md).

# v0.3.0b2 (beta)

- End unconfirmed command assumptions after 30 seconds, independent of polling.
- Keep timed-out activity unknown, notify persistently, and recover only on a later
  matching observation; do not retry or reverse commands automatically.
- Cancel command deadlines on confirmation, replacement, removal or unload.

See [v0.3.0b2 beta notes](docs/releases/v0.3.0b2.md).

# v0.3.0b1 (beta)

- Support Nuki resources with the Fabman access switch and timed activity interval.
- Add Nuki locked-state and battery sensors from Fabman's synchronized status.
- Add read-only POS authorization events for successful Fabman resource-log entries.
- Keep POS resources free of switch and on/off activity entities; omit member data from events.
- Retain Connectivity and resource lifecycle behavior across supported resource types.
- Store incremental POS log cursors without replaying earlier history on first setup.
- Add regression coverage for API pagination, invalid IDs, Nuki states and entity behavior.
- Live Nuki command behavior and Happylab POS/Nuki telemetry remain to be verified.

See [beta notes and HACS installation](docs/releases/v0.3.0b1.md).

# v0.2.0

- Publish the cumulative b1–b6 changes as a stable release, including native Activity
  and Connectivity binary sensors, resource lifecycle synchronization and timed door releases.
- Add optional usage attribution through `fabman.turn_on` with a member ID or email.
- Preserve existing entity identities and API-member defaults; uncertain observations
  use unknown/unavailable rather than an invented off state.
- Update main and README with installation, migration and action documentation.
- Validate with 239 tests on each of Home Assistant 2026.10.1 and 2026.10.2.
- Member reassignment retains the documented correlation and live-validation limits.

See [release notes and upgrade instructions](docs/releases/v0.2.0.md).

# v0.2.0b6 (beta)

- Add `fabman.turn_on` with an optional member ID or exact email address for usage attribution.
- Keep the API-key member as the default; reject both selectors or invalid members before activation.
- Correlate confirmed commands to one new usage and reassign with optimistic locking.
- Serialize local resource commands and report partial failures without repeating activation.
- Refresh README for current entities, discovery, lifecycle, webhooks and beta installation.
- Live reassignment and subsequent hardware updates remain to be validated in a controlled pilot.
- Validate with 239 tests on each of HA 2026.10.1 and 2026.10.2.

See [details and HACS update instructions](docs/releases/v0.2.0b6.md).

# v0.2.0b5 (beta)

- Fix assumed door switches staying on when a short release ends before reconciliation.
- A new successful door grant confirms the opening even if its release already expired.
- Prefer usage IDs over update timestamps; capture the baseline before posting the command.
- Preserve unknown for old grants, offline bridges, denied or invalid usage.
- Validate with 203 tests on HA 2026.10.1 and 2026.10.2 and a targeted authorized live door test.

See [details and HACS update instructions](docs/releases/v0.2.0b5.md).

# v0.2.0b4 (beta)

- Discover new supported resources on all platforms after successful refreshes, without reload.
- Fetch all four lifecycle states and retain known archived/deleted resources as unavailable.
- Preserve IDs and user names across source renames, reload and reactivation.
- Allow manual HA cleanup only for inactive/missing devices after a trustworthy read.
- Preserve lifecycle filters across pagination and cancel inactive door/command state.
- Validate with 193 tests on Home Assistant 2026.10.1 and 2026.10.2.

See [details and HACS update instructions](docs/releases/v0.2.0b4.md).

# v0.2.0b3 (beta)

- Add an enabled Connectivity binary sensor on each supported resource's existing device.
- Use only the explicit boolean `bridge.offline` flag for connectivity.
- Report activity as unknown when the bridge is offline or connectivity is unknown.
- Keep API errors/resource removal unavailable and reuse existing polling/webhooks.
- Preserve entity IDs and validate with 177 tests on HA 2026.10.1 and 2026.10.2.

See [details and HACS update instructions](docs/releases/v0.2.0b3.md).

# v0.2.0b2 (beta)

- Fix false `invalid_stop_timestamp` results for completed machine usage.
  `lastUsed.at` can reflect a log update after `stoppedAt`; it is not a usage start.
- Preserve unknown for invalid timestamps, ambiguous offline stops and null usage.
- Add regression cases based on usage shapes observed in authorized read-only API checks.
- Validate with 155 tests on Home Assistant 2026.10.1 and 2026.10.2.

See [details and HACS update instructions](docs/releases/v0.2.0b2.md).

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
