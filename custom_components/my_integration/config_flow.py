"""Config Flow for Fabman integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_URL

_LOGGER = logging.getLogger(__name__)

DOMAIN = "fabman"

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_URL, default="https://fabman.io/api/v1"): str,
    vol.Required(CONF_API_KEY): str,
})


async def validate_input(hass, data):
    """Validate the user input by making a test API call."""
    # Hier kann ein Testaufruf an die Fabman API eingebaut werden.
    # Beispielsweise:
    from .api import FabmanAPI
    session = hass.helpers.aiohttp_client.async_get_clientsession()
    api = FabmanAPI(session, data[CONF_URL], data[CONF_API_KEY])
    try:
        # Test: Wir rufen einmal die Ressourcen ab (ohne komplette Paginierung – reicht der erste Request?)
        resources = await api.get_resources()
    except Exception as err:
        _LOGGER.exception("Error connecting to Fabman API: %s", err)
        raise Exception("cannot_connect") from err

    # Optional: Weitere Checks (z. B. ob Ressourcen zurückkommen)
    return {"title": "Fabman"}


class FabmanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fabman."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except Exception as err:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors
        )
