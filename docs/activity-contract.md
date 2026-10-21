# Activity implementation: first migration block

This describes the v0.2.0b5 prerelease after v0.1.1. Publishing this beta does not
change any Happylab installation, MQTT service or external webhook. On 2026-10-21
the owner separately authorized two three-second opening tests of one door;
no other equipment or Fabman configuration was changed.

## Scope and evidence

The additional `binary_sensor` reports API-observed resource usage. It does not
measure electrical power, prove a physical relay position or act as a door
contact. Machine sensors use device class `running`. Doors report the timed
electrical release after a successful grant, without a physical door device class.

The interpretation is based on:

- [Fabman activity logs](https://github.com/FabmanHQ/fabman-api/blob/master/sections/log.md):
  `normal`, `automatic`, `filter` and `permission` describe ended activities;
  `takeover` can occur while equipment keeps running, and `offline` has uncertain
  timing. `race` is a technical exceptional case.
- [Fabman usage sessions](https://github.com/FabmanHQ/fabman-api/blob/master/sections/bridges.md#usage-sessions):
  door sessions can already be closed when the bridge opens the door temporarily.
- [Fabman door duration](https://forum.fabman.io/t/feature-request-option-for-how-long-a-door-open/402):
  `maxOfflineUsage` supplies the opening duration. The repository owner confirmed
  that no separate server off event follows the timed release.
- [Fabman resource API announcement](https://www.fabman.io/blog/new-features-analytics-speed):
  resource `lastUsed` details include `stoppedAt` and `stopType`.
- [Public API schema](https://fabman.io/api/v1/swagger.json): bridge commands can
  be pending; resource response schemas are incomplete and do not establish every
  null/missing-field meaning.

On 2026-10-20, authorized read-only queries compared resource summaries with two
corresponding resource-log records. In both cases `lastUsed.at` matched the log's
`updatedAt`, not `createdAt`. Among 105 supported resources, 71 completed machine
usages had valid `stoppedAt` values earlier than `lastUsed.at`. Differences ranged
from one millisecond to several hours. The b1 requirement `stoppedAt >= at` was
therefore incorrect and has been removed. This does not change validation of
missing, malformed, naive or future timestamps. No general usage duration is
derived from resource `lastUsed.at`.

Regression fixtures use synthetic identities and dates with these observed usage
shapes; they contain no member data or API credentials. The following remain open:

- Whether `lastUsed: null` guarantees that the resource has never been used.
- Freshness beyond Fabman's server-reported offline detection (including bridges
  with disabled detection); cloud connectivity is not a physical measurement.
- Offline use that has not yet reached Fabman. An old ended session cannot prove
  current physical inactivity during offline operation.
- Door grant timestamps in actual responses, repeated remote switch-on and
  continuous opening when `maxOfflineUsage` is zero or null.

Until those questions have been verified using redacted responses and a passive
comparison, this implementation is **not approved for production light migration**.
Resource 674 and production door automations remain outside this implementation.

## State contract

The parser never coerces unknown into false. `available = False` takes precedence
over a stored activity value when Home Assistant publishes an entity state.

| Evidence | Activity result | Reason |
| --- | --- | --- |
| Bridge explicitly offline | `unknown` | `bridge_offline` |
| Missing or non-boolean bridge offline flag | `unknown` | `bridge_connectivity_unknown` |
| Machine with explicitly online bridge, valid explicit `lastUsed.at`, explicit `stopType: null`, and no end timestamp | `on` | `usage_active` |
| Same machine, recognized ended stop type, valid nonfuture `stoppedAt`, regardless of its order relative to `at` | `off` | `usage_stopped` |
| `lastUsed` key missing | `unknown` | `usage_missing` |
| Explicit `lastUsed: null` | `unknown` until never-used semantics are verified | `null_usage_unverified` |
| Empty or wrongly typed usage data | `unknown` | `invalid_usage` |
| Missing, invalid or unrecognized stop type | `unknown` | Specific `stop_type_*` reason |
| `offline`, `takeover` or `race` | `unknown` | `ambiguous_stop_*` |
| Missing/invalid/naive/future timestamp, or an active usage with an end timestamp | `unknown` | Timestamp or consistency reason |
| Online door with valid successful grant timestamp and positive finite `maxOfflineUsage`, before deadline | `on` | `door_release_active` |
| Same door at or after `lastUsed.at + maxOfflineUsage` | `off` | `door_release_expired` |
| Door with invalid/unknown duration or grant timestamp | `unknown` | `invalid_door_release_window` |
| Accepted command not confirmed by matching API usage | `unknown` | `command_unconfirmed` |
| API/HTTP/JSON/whole-snapshot failure, or resource absent from a complete snapshot | `unavailable` | Coordinator/resource availability |

Both timestamps must carry a timezone; offsets are compared as absolute instants.
No arbitrary maximum usage age is imposed on a long-running machine. A
session-derived `off` describes the API-reported ended session, not a separately
verified current hardware state. The bridge must additionally be explicitly
online according to the server. Hardware freshness beyond this server flag is
not silently inferred from successful cloud communication.

## Connectivity

Each supported resource has a second enabled binary sensor named **Connectivity**
with HA device class `connectivity`, grouped on its existing device. Its unique ID
is `fabman_connectivity_<entry_id>_<resource_id>`. Home Assistant generates its
entity ID from the device name and Connectivity, and localizes the state labels.

| Evidence | Connectivity | Activity |
| --- | --- | --- |
| `_embedded.bridge.offline: false` | `on` (connected) | Evaluate usage |
| `_embedded.bridge.offline: true` | `off` (disconnected) | `unknown` |
| Offline flag missing, null or wrongly typed | `unknown` | `unknown` |
| API failure or resource absent from complete snapshot | `unavailable` | `unavailable` |

Read-only checks on 2026-10-20 confirmed explicit boolean flags in the existing
paginated `embed=bridge` response, including an offline machine and offline door.
The new sensor reuses the coordinator: no additional HTTP requests or polling loop.
Bridge `inUse`, resource state, timestamps and API success are not substitutes for
the offline flag. In particular, bridge `updatedAt` is not advertised as a generic
last-seen sensor without further verification of its semantics.

This is the server's connectivity assessment. Fabman normally marks a bridge
offline after three missed heartbeat intervals; HA then sees it on the next
poll/webhook refresh. Disabling polling leaves state dependent on successful
webhook delivery. Neither sensor claims immediate physical loss detection.

The same activity protection applies to legacy text sensors and observed switch
states. Pending switch commands retain their explicitly assumed requested state,
without changing Connectivity or confirming usage while offline. Door timers are
cancelled while offline or connectivity is unknown, and reconstructed from the
original grant deadline after a successful online snapshot.

## Commands and ordering

Raw resource data is no longer edited after an HTTP 201 response. A separate
command assumption supplies the existing switch's requested state and sets its
HA `assumed_state` flag. Status sensors and binary activity sensors instead become
unknown while that command lacks matching API usage evidence.
For a light blueprint that only reacts to an explicit `off` to `on` transition,
`off` to `unknown` to `on` during a command does not create that trigger. This
conservative behavior must be included in the later pilot acceptance cases;
production automations are not changed here.

A contradictory machine response does not confirm the command. There is no
invented expiry that turns it into off. The assumption can remain until matching
evidence, another command, disappearance of the resource, reload or unload.
Polling `/bridge-commands/{id}` for actual command completion is not implemented
in this first block. A door switch-on requires a new successful grant in a
subsequent API read. A valid new grant confirms that opening occurred even if
its release window already expired before the read arrived: the assumption is
cleared and the observed state is off, rather than remaining assumed on forever.
No artificial on window is created at that delayed observation time.

When the previous usage has an integer ID, the new grant must have a different
integer ID. A timestamp update of the same usage is insufficient. For older
responses without a baseline usage ID, the timestamp comparison remains a fallback.
Explicit denied usage, offline bridges and invalid release windows cannot confirm
a door opening. The baseline is captured before the command POST, so a new grant
arriving during the POST is not mistaken for the old grant. A bare HTTP 201 never
starts a release timer.

The delayed-expired-grant regression failed on b4 and passed after the fix. A
targeted authorized live check using the corrected switch/coordinator observed
off -> assumed on -> confirmed on -> off with a three-second release.

A revision barrier discards the result or error of a read started before a newer
confirmed update or command. A debounced follow-up fetch is scheduled. Request
bursts continue to use the HA coordinator's locking and debouncing; no independent
parallel polling loop was introduced.

Door release timers publish off locally at `lastUsed.at + maxOfflineUsage`,
without polling or waiting for a server off event. The grant must be represented
in authoritative successful usage data; webhook payloads and accepted commands
alone are insufficient. Door `stopType`/`stoppedAt` do not end the release early,
because the server can close the usage session immediately. Repeated polls of
the same grant keep the original deadline; a later grant establishes a new one.
The source attribute is `door_release_timer`: off means the configured release
window elapsed, not that a physical contact reports a closed door. Zero, null,
negative, infinite and invalid durations remain unknown.

Timers are replaced after accepted snapshots and cancelled on unload. Expiry
notifies listeners without changing raw API data or clearing an API error. An
unavailable entity stays unavailable. A refresh already in flight at unload
cannot publish a newly fetched snapshot.

## Complete snapshots and malformed resources

Pages are fetched atomically using Fabman's `Link` header. Relative links are
resolved against the current page. Cycles, redirects and links outside the
resource endpoint fail closed. When supplied, `X-Total-Count` must agree across
pages and with the number of returned records. A later-page failure never publishes
a shortened list. No snapshot isolation across concurrent Fabman edits is claimed.

An individual record with a valid ID remains in the snapshot even if its usage is
malformed; its activity becomes unknown. Records without a usable ID are counted
and skipped. A nonempty response with no usable IDs, a non-list response or
duplicate resource IDs invalidates the snapshot. Exceptions and HTTP failures do
not log raw response bodies, API tokens, member names or transport exception text.
HTTP 429 records a retry cooldown; subsequent refresh requests cannot bypass the
server's numeric `Retry-After` delay (at least two seconds).

## Resource inventory and lifecycle

The API explicitly requests all states (`active`, `locked`, `archived`, `deleted`)
using repeated `state` query parameters. Fabman's default active/locked filter
cannot distinguish archival from disappearance. Pagination preserves these
filters and bridge embedding when relative next links omit them; narrowed state
filters fail the snapshot. A read-only check confirmed the query in the real API.

Each platform listens for accepted coordinator updates. New active/locked supported
resources get entities once; entity-registry removal clears the corresponding
tracking entries, including for disabled entities. Discovery listeners are removed
on config-entry unload. Existing registry entries for archived/deleted resources
are restored as unavailable on reload; historical inactive resources without such
entries are not newly created. Missing resources retain registry entries without
automatic deletion. The `resource_state` attribute distinguishes lifecycle values,
missing resources and unknown explicit states. Absent state fields retain the
previous active assumption for backward compatibility.

Archival/deletion prevents availability and switch commands, clears pending
command assumptions and cancels door timers. Reactivation without manual cleanup
reuses identities. Source renames update default device/status/switch names,
without changing entity IDs, user-provided names, areas or disabled preferences.

`async_remove_config_entry_device` permits user-initiated local cleanup for
archived/deleted or absent resources only after a successful complete inventory
with no unidentified malformed rows. Active/locked devices and API-error states
refuse removal. This does not send a deletion to Fabman. Inactive removed devices
are not rediscovered until reactivated. No automation inputs are rewritten: users
must review references to retired equipment because unavailable inputs can block
automatic light-off. Repeated successful snapshots never remove registry devices
automatically in this migration pilot.

## Compatibility and remaining work

- Existing sensor/switch unique IDs and device identifiers are unchanged. New IDs
  include config entry ID and resource ID, so repeated resources in two connections
  do not collide among the new binary sensors. Legacy ID overlaps are explicitly
  logged; legacy entity IDs are not silently migrated or repaired.
- Existing text status sensors now return unknown for unverified cases instead of
  false inactivity, including invalid door windows and null usage. This intentional
  behavior correction must be considered when testing existing automations.
- Existing common and entry-specific webhook URLs remain supported. Webhooks
  trigger authoritative reads and never directly trust usage from their payloads.
- Polling remains enabled by default at 30 seconds. With polling disabled, a
  silently lost webhook does not automatically expire a last known machine state;
  webhook-only operation is not approved for the migration.
- Activity attributes contain resource ID/type/state, status source and reason.
  Last successful fetch time and resource counts live on the coordinator, rather
  than changing every activity entity's attributes on every poll.
- New supported resources are discovered after successful refreshes on all three
  platforms, without reload. Options flow, initial connection validation and
  broader diagnostics remain future work.

## Passive test preparation

Run the suite with synthetic API responses on HA 2026.10.1 and 2026.10.2. No real
switch commands are needed. Before a separately authorized pilot, verify redacted
machine/bridge examples including never-used, offline and takeover cases, agree
on acceptable end-to-end latency, and compare activity states in parallel with the
existing system. MQTT values alone are not an independent freshness reference.

HA 2023.1.0 remains the existing advertised HACS minimum; this work does not claim
that historical version has been tested. The migration test targets are explicitly
2026.10.1 and 2026.10.2. Publishing a prerelease does not authorize changes to a
running installation or migration of its production automations.
