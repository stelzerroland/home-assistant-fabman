# Fabman integration for Home Assistant

Monitor and control Fabman resources from Home Assistant. `machine`, `door` and
`nuki` resources with a bridge have controls and activity sensors. `pos` resources
are read-only and report successful authorization events. `checkIn` terminals are
read-only: they expose bridge connectivity and contribute space-level attendance
entities with member lists and check-in/check-out events.

The current stable release is **v0.2.0**, incorporating the changes from betas
b1–b6, including activity/connectivity entities, resource synchronization and
optional usage member assignment. The **v0.3.0b1 beta** adds read-only POS events
and Nuki access, lock-state and battery entities for live testing.
The check-in attendance support described below is implemented in the development
branch and is **not yet included in a published release**.
Compare states with your existing installation before migrating automations.
The integration remains under active development. Tested behavior and remaining
limitations are documented below; testing and feedback are welcome.

Initial integration setup is available entirely through the Home Assistant UI;
no YAML configuration is required. YAML examples below are optional action examples.

## Devices and entities

Each supported resource has one device with the applicable entities below.
Check-in terminals have Connectivity only; their shared attendance sensor and
event entity belong to a separate **Fabman – <space name>** service device.

| Entity | Meaning |
| --- | --- |
| Switch named after the resource | For machine, door and Nuki: sends Fabman bridge on/off commands using the configured API key |
| Activity binary sensor | Machine usage or the timed door/Nuki access interval: `on`, `off`, or `unknown` |
| Connectivity binary sensor | Fabman bridge connectivity from its explicit `bridge.offline` flag |
| Legacy text Status sensor | Activity as text `on`/`off`; retained for existing installations |
| Nuki Lock binary sensor | Current lock state reported by Fabman (`on` means unlocked); transitions and unknown states stay unknown |
| Nuki Battery sensor | Battery percentage reported by Fabman |
| POS Authorization event | A successful (`allowed`) POS authorization from Fabman's resource log |
| Checked-in members sensor (per space) | Number of distinct checked-in members, with their current list in `members` |
| Check-in activity event (per space) | `checked_in` and `checked_out`, including the affected Fabman member |

POS resources have no switch or activity state in this integration. Fabman POS
bridges perform authorization checks and do not switch equipment on/off like a
normal bridge. The event entity reports successful authorizations only; it does
not represent the physical POS terminal's power or a running session. Its
Connectivity sensor reports the Fabman bridge, not the POS terminal. Historical
POS authorizations are not replayed when the integration is first set up. New
events are collected during the configured polling refresh or a webhook-triggered
refresh.

For Nuki, **Activity** is the Fabman access pulse and turns off locally after
`maxOfflineUsage`, while the **Lock** binary sensor is the separate lock state
(`on` means unlocked, following Home Assistant's lock device class). The switch's
`turn_on` uses the action configured for that resource in Fabman; it is not a
general-purpose Home Assistant lock/unlock control. Nuki status and battery come
from Fabman's synchronized Nuki data. The `Connectivity` sensor still describes
the Fabman bridge. Nuki Opener or Box state codes are not treated as lock states;
their **Lock** entity remains unknown.

An accepted switch command initially produces an **assumed** switch state. It
does not establish that the resource is actually running. API observations confirm
the state. Ambiguous or invalid usage and offline/unknown bridge connectivity
make activity unknown. Failed API reads make the entities unavailable.

Command confirmation has a **30-second local timeout**, including when periodic
sync is disabled or API reads fail. Without a matching observation, the assumed
switch state ends, Switch/Activity/Status remain unknown, and Activity/Status expose
`status_reason: command_timeout` instead of `command_unconfirmed`. A persistent HA
notification explains the failure. An unchanged old door grant cannot clear this
error; a later matching observation can, and dismisses the notification. The timeout
does not retry activation, send a switch-off, or cancel a pending command at Fabman.
Check the server/hardware before retrying. Timeout state is local and is not
preserved across an integration reload or HA restart. Custom dashboard cards must
use `command_timeout` to distinguish a failed confirmation from ongoing waiting.

For doors, Activity represents an allowed **release interval**, not a physical
door contact. It remains on for `maxOfflineUsage` seconds after the reported grant
and then turns off locally, including when Fabman sends no later off event.
See the [activity contract](docs/activity-contract.md) for exact semantics and
migration limitations, including never-used resources.

## Read-only check-in terminals and attendance

For every space with a supported current `checkIn` terminal, the integration adds
one **Fabman – <space name>** service device. Multiple terminals in the same space
share its attendance entities. No switch or check-in/out command is created for a
terminal. Existing switches become unavailable if their resource is reconfigured
as a POS or check-in terminal.

**Checked-in members** has the number of distinct members as its numeric state.
Its `members` attribute is a list of objects containing `member_id`, `name`,
`checked_in_at` (the earliest currently open session) and `resource_ids`.
Multiple open sessions for the same member in one space count as one person;
they remain on the list until their last session ends. `active_sessions` gives
the separate session count and `last_successful_sync` shows the last good read.
Example attributes, using synthetic data:

```yaml
space_id: 5
active_sessions: 1
members:
  - member_id: 12345
    name: Example Member
    checked_in_at: "2026-10-22T07:50:00+00:00"
    resource_ids: [1370]
```

**Check-in activity** reports `checked_in` or `checked_out`. Each event contains
`account_id`, `space_id`, `member_id`, `member_name`, `log_id`, `resource_id`,
`occurred_at`, `observed_at` and `stop_type`. `resource_id` is the resource assigned
to that session; it must not be interpreted as proof of which terminal performed
the checkout. `occurred_at` is Fabman's activity timestamp; `observed_at` is when
the integration detected it. A short visit between polling refreshes produces
both events in chronological order, even if the current member count is already
zero. Trigger automations on new event occurrences, rather than only on changes
to the `event_type` attribute: consecutive events can have the same type.

On HA startup or integration reload the list is rebuilt from all active check-in
logs, without replaying historical or downtime events. During normal operation
the integration also reads recent completed sessions and re-reads previously
open sessions that disappear, so a checkout is detected even if the check-in was
days earlier. API failures retain the last list as attributes but make the space
entities unavailable; other devices and terminal Connectivity continue working.
An offline terminal does not check its members out. Backdated administrative
corrections update the list without replaying events older than the tracking
window. These are Fabman's recorded check-ins, not independent physical-presence
detection. Names and IDs are exposed deliberately; email, contact, billing and
other member-profile fields are not copied into these entities.

Attendance uses the configured polling interval (30 seconds by default) and the
existing webhook-triggered refresh. Subscribe the Fabman webhook to **Activity
log** updates for faster detection. With polling disabled a working webhook is
required for ongoing updates. An automation can use a member-count transition
from zero to a positive number for the first arrival, or to zero for the last
departure. Use the list attribute to render currently checked-in names on a
dashboard. Use member IDs, rather than names, to identify people in automations.

## Resource synchronization

Successful complete API refreshes discover new supported active/locked resources
without restarting HA. Known archived, deleted or missing resources remain in HA
as unavailable; their entity identities are retained rather than automatically
deleted. You can remove such devices manually from HA after a successful complete
inventory read. This only removes the HA device, not the resource in Fabman.

Reactivated resources retain their identities unless manually removed. Fabman
renames update default names while preserving HA name overrides and entity IDs.
Resources without a supported bridge do not create new devices.

## Installation and updates

### HACS

HACS must already be installed. Open its **Custom repositories** dialog from the
three-dot menu to add this repository.

1. Add `https://github.com/stelzerroland/home-assistant-fabman` as a custom
   repository with category **Integration** in HACS.
2. Download the integration and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Fabman**.
4. Enter the API token and the API URL for your Fabman deployment.
5. Keep periodic synchronization enabled unless you have a working webhook setup.
   The default interval is **30 seconds**; configuration accepts 10–3600 seconds.

The API token determines whose permissions are used for remote commands and whose
member account initially owns the resulting usage. Use an account with the
necessary Fabman permissions. Keep the token secret.

To update, open Fabman in HACS and install **v0.2.0**. If you previously selected
a beta manually, choose **Redownload → Need a different version? → v0.2.0**.
Beta/prerelease versions do not need to be enabled for this stable release.
Read the [v0.2.0 release notes](docs/releases/v0.2.0.md) before updating from v0.1.1.
Restart HA after updating the integration's Python code; reloading its entry alone
does not load the new code. Updates preserve existing configuration and entity
identities. However, legacy status sensors also adopt the new unknown/unavailable
semantics when upgrading from v0.1.1, so
check automations that depend on their previous behavior before updating.
For a rollback, select v0.1.1 and restart again; that version lacks the native
activity/connectivity sensors, resource lifecycle handling and member action.

To try the **v0.3.0b1 beta**, open Fabman in HACS, choose **⋮ → Redownload**,
enable **Show beta versions**, select **v0.3.0b1**, download it and restart Home
Assistant. To return to stable, repeat these steps with beta versions disabled and
select **v0.2.0**. Review the [beta release notes](docs/releases/v0.3.0b1.md)
before testing; POS authorizations are events rather than on/off state, and Nuki
commands and telemetry have not yet been validated against Happylab hardware.

### Manual installation

Copy `custom_components/fabman` into `/config/custom_components/fabman`, restart HA,
then add the integration as described above. Install v0.2.0 for stable features
or v0.3.0b1 to test POS and Nuki support.

## Optional member assignment

The additional **Fabman: Turn on** action (`fabman.turn_on`) can assign the
resulting usage to a different Fabman member. Existing switch controls keep their
behavior. No extra entity, global default or HA-user mapping is introduced.

Use it in **Developer tools → Actions**, a script, an automation or a dashboard
button. Select a Fabman switch and provide **either** `member_id` **or**
`email_address`. The entity IDs below are examples; choose your actual switch.

```yaml
action: fabman.turn_on
target:
  entity_id: switch.eingang_office_og
data:
  email_address: member@example.com
```

Alternatively:

```yaml
action: fabman.turn_on
target:
  entity_id: switch.laser_thunder_nova_63
data:
  member_id: 12345
```

Omit both fields to use the API-key member as usual. Supplying both is rejected
before activation. Member IDs must be positive integers. An email search must
return exactly one result with the exact email address, ignoring case. A missing,
ambiguous or cross-account member aborts before activation; there is no silent
fallback to the API member. If a text search is ambiguous, use the numeric ID.

The integration validates the member and reads a fresh usage baseline, sends one
remote activation, waits up to 30 seconds for its confirmed execution and assigns
the matching new log entry using `PUT /resource-logs/{id}` with the current
`lockVersion`. It does not change an already-running machine session. It serializes
activation commands for the same resource within one integration entry. Explicit
off commands remain immediate and do not wait for assignment to finish.

Fabman does not document a direct usage ID in the activation response. Matching
therefore requires exactly one allowed usage in the command's creation-to-completion
time window, on the same account/resource, initially belonging to the command's
member and different from the baseline. Missing or multiple matches are rejected.
This is correlation rather than an atomic server-side transaction; external
simultaneous controls cannot be locked by HA. Do not use this as a guaranteed
attribution mechanism for concurrent external controls.

If activation has already been accepted but assignment fails, the action raises a
clear HA error. The resource may already be on, and the usage may still belong to
the API member. Inspect the activity log; do not repeat activation merely to retry
assignment. The integration does not retry activation, automatically switch off,
or overwrite an assignment conflict. A restart during the operation can also
leave attribution incomplete; pending assignments are not persisted.

**Activation uses the configured API account's permissions.** Reassigning a log
does not check the selected member's training, access rights or presence. It can
affect that member's charges, packages and discounts. Normal HA entity-control
permissions apply to the action. There is no automatic mapping from the HA caller
to a Fabman member.

Switch off through `switch.turn_off` as usual. For an assigned door usage, HA keeps
the verified original log creation time in memory so changing the member does not
extend the release through a changed log-update timestamp. This anchor is not
persisted across reloads/restarts; after a restart, the normal API-based activity
rules apply. Local HTTP tests cover assignment for machine and door logs; reassignment
of live hardware sessions, subsequent bridge updates and the bridge's displayed
member still require a controlled pilot before relying on the feature.

References: [Fabman API schema](https://fabman.io/api/v1/swagger.json),
[reassigning activity and related charges](https://help.fabman.io/article/39-reassign-activity).

## Optional webhooks

Polling works without inbound access to HA. Webhooks require an HTTPS endpoint
that the Fabman server can reach from the internet. Possible setups include
port forwarding with dynamic DNS (for example DuckDNS), or a tunnel such as
Cloudflare Tunnel without inbound port forwarding. These are external networking
options, not features configured by this integration.

The previous README included these community setup videos, retained as optional
background material: [DuckDNS tutorial](https://www.youtube.com/watch?v=AK5E2T5tWyM)
and [Cloudflare Tunnel tutorial](https://www.youtube.com/watch?v=JGAKzzOmvxg).
They have not been revalidated against current software versions.

In Fabman:

1. Sign in to the admin interface.
2. Open **Configure → Integrations (API & Webhooks)**.
3. Choose **Add Webhook**.
4. Set the event type to **Activity Log** and enter the URL below.
5. Save the webhook settings.

```text
https://<your-ha-host>/api/webhook/fabman_webhook
```

This legacy URL refreshes all configured Fabman connections. For one connection,
use `/api/webhook/fabman_webhook_<entry_id>`. Find its entry ID in
**Developer tools → Template**:

```jinja
{{ config_entry_id('switch.your_fabman_resource') }}
```

Replace the example entity ID with a switch belonging to that connection. See the
[HA template reference](https://www.home-assistant.io/template-functions/config_entry_id/).
An entry-specific webhook refreshes only its own connection. Resource state and
door timeout settings are always read from Fabman, not supplied by the webhook.

Webhook payloads trigger an authoritative API refresh; they do not directly replace
resource state. Webhooks are not an independent state source and do not eliminate
API calls. Keep polling enabled as a reconciliation mechanism, especially for
inventory changes that may not emit an Activity Log event. In webhook-only mode,
inventory discovery requires a webhook or another successful refresh.

## Release history and future development

The [changelog](CHANGELOG.md) and [individual beta release notes](docs/releases)
retain the detailed history: corrected completed-usage timestamps (b2),
Connectivity (b3), resource lifecycle synchronization (b4), and confirmation of
short door releases that have already expired when read (b5). A targeted live
door release check passed for b5; broader production comparison remains necessary.
Activity and Connectivity share the existing polling/webhook resource reads and
do not require separate polling requests.

POS authorization monitoring and Nuki status are available for beta testing in
v0.3.0b1. Further Fabman API support and extended equipment information remain
possible future work. Power measurements and general resource-log history are not
provided as entities. Resource synchronization, previously listed as planned, is
implemented in v0.2.0 as described above.

## Development

Regression tests run against Home Assistant **2026.10.1 and 2026.10.2**, on Python
3.14. These are the tested versions, not a claim of compatibility with every HA
release.

```sh
python -m venv .venv
# Activate the environment in your shell, then:
python -m pip install -r requirements-test.txt
python -m pytest
python -m ruff check --isolated --select E4,E7,E9,F custom_components tests
```

See [CHANGELOG.md](CHANGELOG.md) and [release notes](docs/releases) for previous
changes. Report bugs or propose improvements through this repository's issues
and pull requests. Avoid including API tokens or personal member data in reports.

Made with ❤️ for Makerspaces!
