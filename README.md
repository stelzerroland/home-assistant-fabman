# Home Assistant Fabman Integration (⚠️ Alpha Version)

⚠️ **This integration is in an early development stage!**  
🚧 **NOT ready for production use – testing & feedback welcome!**  

This **custom integration** for **Home Assistant** allows you to display and control machines from **Fabman** as Home Assistant devices.  
Status updates can be received either via **polling** (default) or optionally via **Webhooks** for real-time updates.  

## 🚀 Features (Current State)
✅ **Automatic discovery** of all Fabman resources via API  
✅ **Status monitoring** of machines as **sensors** (on/off)  
✅ **Control machines** with a Fabman Bridge via **switch entities**  
✅ **HACS support** (easy installation & updates)  
✅ **Fully configurable via the Home Assistant UI** (no YAML required)  
✅ **Optional Webhook support for real-time updates**  

⚠️ **Known Limitations:**  
❌ **Webhook setup requires an externally accessible Home Assistant instance** (see setup details below).  
❌ **Limited testing** – expect potential bugs & issues!  
❌ **Currently, only basic Fabman API functions are used** – future enhancements planned.  

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

## 🔮 Planned Features (Future Development)
🟢 **Automatic synchronization of new/removed Fabman resources**  
🟢 **Extended machine information (power usage, sensors, logs)**  
🟢 **Support for more Fabman API features**  

## 🛠 Feedback & Development
❗ **This integration is under active development & not stable yet!**  
💡 **Bug reports & feature requests are welcome!**  
📩 If you want to contribute, please open a **GitHub Issue** or a **Pull Request**.  

---

**Made with ❤️ for Makerspaces!** 🚀

