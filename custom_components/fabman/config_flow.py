import voluptuous as vol
from homeassistant import config_entries
from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_ENABLE_PERIODIC_SYNC,
    CONF_POLL_INTERVAL,
    DEFAULT_API_URL,
    DEFAULT_ENABLE_PERIODIC_SYNC,
    DEFAULT_POLL_INTERVAL,
)

class FabmanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow for Fabman Integration."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Optional: Hier kann eine Verbindung zum Fabman API-Test implementiert werden.
            return self.async_create_entry(title="Fabman", data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_API_TOKEN): str,
            vol.Optional(CONF_API_URL, default=DEFAULT_API_URL): str,
            vol.Optional(CONF_ENABLE_PERIODIC_SYNC, default=DEFAULT_ENABLE_PERIODIC_SYNC): bool,
            vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL):
                vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)
