# Setting Up Home Assistant on Raspberry Pi with Fabman Integration & Cloudflare Tunnel

This guide outlines the complete setup process for Home Assistant on a Raspberry Pi, installing the Fabman integration, and configuring a Cloudflare Tunnel for secure external access and webhook support.

## **1. Prerequisites**
- Raspberry Pi (Recommended: Raspberry Pi 4)
- SD card (Minimum 16 GB)
- Fabman account & configured Fabman bridge
- Cloudflare account & domain (optional but recommended)

---

## **2. Installing Home Assistant on Raspberry Pi**
Follow this video guide for installing Home Assistant OS on a Raspberry Pi:  
📺 [YouTube: Installing Home Assistant on Raspberry Pi](https://www.youtube.com/watch?v=xSqopd0eARI)

After installation:
1. **Open Home Assistant:** `http://<raspberrypi-ip>:8123`  (e.g., `http://192.168.0.151:8123` or `http://homeassistant.local:8123`)
2. **Complete initial setup:** Create a user account, change server name (Settings → System → Network)

---

## **3. Installing HACS (Home Assistant Community Store)**
HACS allows installing custom integrations.
1. **Add HACS repository as an Add-on:**
   - Go to **Settings → Add-ons → Add-on Store**
   - Click `... → Repositories`
   - Add: `https://github.com/hacs/addons` → **Add**
2. **Install HACS:**
   - Open [HACS Supervisor Link](https://my.home-assistant.io/redirect/supervisor_addon/?addon=cb646a50_get&repository_url=https%3A%2F%2Fgithub.com%2Fhacs%2Faddons)
   - Enter Home Assistant URL (e.g., `http://192.168.0.151:8123`)
   - Click **“Get HACS” → Install**
   - **Restart Home Assistant** (Settings → System → Restart)
3. **Add HACS as an integration:**
   - **Settings → Devices & Services → Add integration → “HACS”**
   - Follow the instructions (GitHub account required)

---

## **4. Installing Fabman Integration**
1. **Add Fabman Integration in HACS:**
   - **HACS → `...` → Custom repositories**
   - Add: `https://github.com/stelzerroland/home-assistant-fabman` (Type: **Integration**)
2. **Install Fabman Integration:**
   - **HACS → Search for “Fabman Integration” → Install**
   - **Restart Home Assistant**
3. **Create Fabman API Key:**
   - Go to Fabman: **Configure → API & Webhooks**
   - [Create an API Key](https://help.fabman.io/article/80-api-key)
4. **Set up Fabman Integration in Home Assistant:**
   - **Settings → Devices & Services → Add integration → “Fabman Integration”**
   - Enter the API token and save

📖 [Official Fabman Integration Documentation](https://github.com/stelzerroland/home-assistant-fabman/blob/main/README.md)

---

## **5. Installing File Editor in HA**
Since `configuration.yaml` needs to be edited, a File Editor is required.
1. **Go to:**
   - **Settings → Add-ons → Add-on Store**
   - Search for **“File Editor”** → Install
2. **Enable all options:** (Start on boot, Show in Sidebar, Watchdog) → **Start**

---

## **6. Making Home Assistant Accessible via Cloudflare Tunnel**
### **Set Up Cloudflare & Register a Domain**
1. **Create a Cloudflare account:** [Cloudflare Sign-Up](https://dash.cloudflare.com/sign-up)
2. **Add a domain to Cloudflare:** If you don’t have one, you can register one for about $10/year.

### **Install Cloudflare Tunnel in HA**
1. **Install Cloudflared Add-on:**
   - **Settings → Add-ons → Add-on Store**
   - **Add repository:** `https://github.com/brenner-tobias/ha-addons`
   - **Search for “Cloudflared” → Install**
2. **Set up Cloudflare Tunnel:**
   - **Settings → Add-ons → Cloudflared → Configuration**
   - Enter your **domain** under "External Home Assistant Name" (e.g., `homeassistant-external.org`) → **Save**
   - **Go to Info tab → Enable "Start on Boot" → Start**
   - **Open the Log tab** → Click the Cloudflare login link, open it in a browser, and confirm the domain

### **Allow Cloudflare as a Trusted Proxy**
1. **Edit `configuration.yaml` using File Editor:**
   ```yaml
   http:
     use_x_forwarded_for: true
     trusted_proxies:
       - 172.30.33.0/24
   ```
2. **Restart Home Assistant:**
   - **Settings → System → Developer Tools → Restart**

Now Home Assistant is accessible at **`https://homeassistant-external.org`** from anywhere. 🎉

---

## **7. Setting Up Webhooks in Fabman**
To ensure status updates from Fabman are instantly sent to Home Assistant:
1. **Log into Fabman** (as Admin/Owner)
2. **Go to:** `Configure → Integrations (API & Webhooks) → Add Webhook`
3. **Enter the following details:**
   - **URL:** `https://<your-external-ha-server>/api/webhook/fabman_webhook`  
     (e.g., `https://homeassistant-external.org/api/webhook/fabman_webhook`)
   - **Descriptive label:** e.g., "Home Assistant"
   - **Event Types:** Select "Activity log"
   - **Save**
4. **Test:** Click **“Send test event”** → If "200 OK" appears, the connection works. ✅

---

## **🎉 Done! Your Home Assistant is now fully set up with Fabman & Cloudflare.**
✅ **HA runs on Raspberry Pi**
✅ **Fabman Integration is active**
✅ **Cloudflare Tunnel allows secure access without port forwarding**
✅ **Webhooks ensure real-time updates from Fabman**

🚀 **Enjoy your new Home Assistant-Fabman integration!** 🚀