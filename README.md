# Home Assistant Fabman Integration (⚠️ Alpha Version)

⚠️ **This integration is in an early development stage!**  
🚧 **NOT ready for production use – testing & feedback welcome!**  

This **custom integration** for **Home Assistant** allows you to display and control machines from **Fabman** as Home Assistant devices.  
Currently, **status updates rely on polling** – **WebSocket support is not yet implemented**.  

## 🚀 Features (Current State)
✅ **Automatic discovery** of all Fabman resources via API  
✅ **Status monitoring** of machines as **sensors** (on/off)  
✅ **Control machines** with a Fabman Bridge via **switch entities**  
✅ **HACS support** (easy installation & updates)  
✅ **Fully configurable via the Home Assistant UI** (no YAML required)  

⚠️ **Known Limitations:**  
❌ **No real-time updates yet** – WebSockets/Webhooks are not implemented (status updates may be delayed due to polling).  
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

## 🔮 Planned Features (Future Development)
🟢 **WebSocket support for real-time updates**  
🟢 **Automatic synchronization of new/removed Fabman resources**  
🟢 **Extended machine information (power usage, sensors, logs)**  
🟢 **Support for more Fabman API features**  

## 🛠 Feedback & Development
❗ **This integration is under active development & not stable yet!**  
💡 **Bug reports & feature requests are welcome!**  
📩 If you want to contribute, please open a **GitHub Issue** or a **Pull Request**.  

---

**Made with ❤️ for Makerspaces!** 🚀

