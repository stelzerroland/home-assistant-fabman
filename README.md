# Home Assistant Fabman Integration (⚠️ Alpha Version)

⚠️ **This integration is in an early development stage!**  
🚧 **NOT ready for production use – testing & feedback welcome!**  

This **custom integration** for **Home Assistant** allows you to display and control machines from **Fabman** as Home Assistant devices.  
Status updates can be received either via **polling** (default) or optionally via **Webhooks** for real-time updates.  

## 🚀 Features (Current State)

The `v0.2.0b5` prerelease adds native `binary_sensor` activity entities alongside
the existing sensors and switches. Unknown or inconsistent usage is reported as
`unknown`, and failed reads or missing resources as `unavailable`. A pending switch
command is an explicitly assumed switch state and does not count as observed
activity. Door release stays on for `maxOfflineUsage` seconds after a reported
successful grant, then turns off locally without a server off event. This is no
physical door contact. Never-used/null semantics await verification.
See the [activity contract and migration limitations](docs/activity-contract.md)
before preparing a passive pilot. A targeted live door release check passed;
broader production comparison remains necessary.
Beta 2 fixes false unknown states for completed machine usage: `lastUsed.at`
can reflect a log update after `stoppedAt` and must not be treated as usage start.
The correction was checked against read-only API data; no hardware was switched.
Beta 3 adds a **Connectivity** binary sensor to each supported device, using
Fabman's explicit `bridge.offline` flag. Offline or unknown connectivity makes
Activity unknown; API failures make both sensors unavailable. Existing text
status sensors follow the same activity rule. Both sensors share polling/webhooks
and require no additional API calls.
Beta 4 discovers new supported resources automatically after successful refreshes.
Known archived/deleted resources remain unavailable and can be removed locally
from HA after a trustworthy inventory check. Reactivation retains identities
unless manually cleaned up. Source renames preserve HA overrides and entity IDs.
Beta 5 clears an assumed door-on command when a new successful release is
already expired by the time reconciliation reads it. Old grants do not confirm
new opens; the usage baseline is captured before posting the command.

To test the beta, open Fabman in HACS, choose **Redownload**, select
**Need a different version?**, and choose `v0.2.0b5`. Enable prerelease/beta versions
if your HACS version requires it. Restart Home Assistant after downloading.
Existing configuration and entity identities are preserved. This beta changes
existing status sensors too: uncertain usage becomes `unknown`, and accepted
commands are assumed switch states until confirmed. See the
[beta release notes](docs/releases/v0.2.0b5.md) before updating. To return to the
stable version, select `v0.1.1` in HACS and restart Home Assistant again.

✅ **Automatic discovery** of all Fabman resources via API  
✅ **Status monitoring** of machines as **sensors** (on/off)  
✅ **Control machines** with a Fabman Bridge via **switch entities**  
✅ **HACS support** (easy installation & updates)  
✅ **Fully configurable via the Home Assistant UI** (no YAML required)  
✅ **Optional Webhook support for real-time updates**  

⚠️ **Known Limitations:**  
❌ **Webhook setup requires an externally accessible Home Assistant instance** (see setup details below).  
❌ **Only Bridge Types "machine" and "door" are supported**
❌ **Currently, only basic Fabman API functions are used** – future enhancements planned.  
❌ **Limited testing** – expect potential bugs & issues!  

## 🔧 Installation via HACS
1️⃣ **Ensure HACS is installed in Home Assistant**  
2️⃣ **Add this repository to HACS**:
   - Open **HACS → Integrations**  
   - Click on the three-dot menu → **Custom repositories**  
   - Enter the following repository:
     ```
     https://github.com/stelzerroland/home-assistant-fabman
     ```
   - Choose **Integration** as the category

3️⃣ **Install the integration & restart Home Assistant**  
4️⃣ **Go to Settings → Devices & Services → Add Integration**  
5️⃣ Search for `"Fabman"` and enter your **API URL** & **API Token**  

## 🔧 Manual Installation (Without HACS)
1️⃣ **Copy the files** to: /config/custom_components/fabman/

2️⃣ **Restart Home Assistant**  
3️⃣ **Go to Settings → Devices & Services → Add Integration**  
4️⃣ Search for `"Fabman"` and enter your credentials  

## ⚡ Optional: Webhook Support for Real-Time Updates
Instead of relying on periodic polling, Fabman Webhooks can be configured for real-time status updates. To use this feature, your Home Assistant instance **must be accessible via HTTPS from the internet**.

### 🔧 Prerequisites
- Your Home Assistant server must be reachable externally via **HTTPS**.
- This can be achieved using:
  - **Port forwarding on your router** and services like **DuckDNS** if you don’t have a static IP address.  
    👉 For setup guidance, refer to resources like [this DuckDNS tutorial](https://www.youtube.com/watch?v=AK5E2T5tWyM).
  - **Alternative without port forwarding:** You can use **Cloudflare Tunnel** to expose Home Assistant securely over HTTPS without opening ports on your router.  
    👉 Learn how to set it up with this **Cloudflare Tunnel tutorial**: [YouTube: Secure Home Assistant with Cloudflare](https://www.youtube.com/watch?v=JGAKzzOmvxg).

### Webhook Setup in Fabman
1️⃣ Log in to your Fabman admin panel.  
2️⃣ Navigate to **"Configure" → "Integrations (API & Webhooks)"**.  
3️⃣ Click **"Add Webhook"**.  
4️⃣ Configure the webhook as follows:
   - **URL:** `https://<your-server>.duckdns.org:8123/api/webhook/fabman_webhook`  
   - **Event Type:** `Activity Log`

5️⃣ Save the webhook settings.  

The existing `/api/webhook/fabman_webhook` URL remains supported and refreshes
all configured Fabman connections. For multiple connections, use a separate URL
for each one: `/api/webhook/fabman_webhook_<entry_id>`. To find the entry ID,
evaluate `{{ config_entry_id('switch.your_fabman_resource') }}` under
**Developer Tools → Template**, replacing the entity ID with one of that
connection's switches. See the [Home Assistant template reference](https://www.home-assistant.io/template-functions/config_entry_id/).
Entry-specific webhooks refresh only their own connection. Resource states and
door timeout settings are always read from the Fabman API.

## 🔮 Planned Features (Future Development)
🟢 **Automatic synchronization of new/removed Fabman resources**  
🟢 **Extended machine information (power usage, sensors, logs)**  
🟢 **Support for more Fabman API features**  

## 🛠 Feedback & Development

Regression tests use Python 3.14 and Home Assistant 2026.10.2:

```sh
python -m venv .venv
# Activate .venv in your shell, then:
python -m pip install -r requirements-test.txt
python -m pytest
```

❗ **This integration is under active development & not stable yet!**  
💡 **Bug reports & feature requests are welcome!**  
📩 If you want to contribute, please open a **GitHub Issue** or a **Pull Request**.  

---

**Made with ❤️ for Makerspaces!** 🚀

