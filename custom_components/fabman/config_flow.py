import voluptuous as vol
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .assignment import MemberAssignment, positive_id
from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_ENABLE_PERIODIC_SYNC,
    CONF_POLL_INTERVAL,
    CONF_USER_MEMBER_MAP,
    DEFAULT_API_URL,
    DEFAULT_ENABLE_PERIODIC_SYNC,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)


class FabmanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow for Fabman Integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="Fabman", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_API_TOKEN): str,
                vol.Optional(CONF_API_URL, default=DEFAULT_API_URL): str,
                vol.Optional(
                    CONF_ENABLE_PERIODIC_SYNC, default=DEFAULT_ENABLE_PERIODIC_SYNC
                ): bool,
                vol.Optional(
                    CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the per-entry user-to-member mapping flow."""
        return FabmanOptionsFlow()


class FabmanOptionsFlow(config_entries.OptionsFlowWithReload):
    """Manage Home Assistant user to Fabman member mappings."""

    async def async_step_init(self, user_input=None):
        """Show mapping management actions and the mappings already stored."""
        mappings = self._mappings()
        all_users = await self.hass.auth.async_get_users()
        user_names = {user.id: user.name or user.id for user in all_users}
        overview = [
            f"{user_names.get(user_id, user_id)} → Fabman {member_id}"
            for user_id, member_id in mappings.items()
        ]
        return self.async_show_menu(
            step_id="init",
            menu_options=(
                ["add_mapping", "remove_mapping"] if mappings else ["add_mapping"]
            ),
            description_placeholders={
                "mappings": "\n".join(overview) or "No mappings configured"
            },
        )

    async def async_step_add_mapping(self, user_input=None):
        """Add or replace one HA user's Fabman member mapping."""
        users = await self._active_users()
        if not users:
            return self.async_abort(reason="no_users")

        errors = {}
        if user_input is not None:
            user_id = user_input.get("ha_user")
            if user_id not in {user.id for user in users}:
                errors["base"] = "invalid_user"
            else:
                raw_member = user_input.get("fabman_member", "").strip()
                member_id = None
                email_address = None
                if raw_member.isascii() and raw_member.isdecimal():
                    candidate = int(raw_member)
                    if positive_id(candidate):
                        member_id = candidate
                    else:
                        errors["base"] = "invalid_member_format"
                elif "@" in raw_member:
                    email_address = raw_member
                else:
                    errors["base"] = "invalid_member_format"

                if not errors:
                    coordinator = self.hass.data.get(DOMAIN, {}).get(
                        self.config_entry.entry_id
                    )
                    if coordinator is None or not coordinator.data:
                        errors["base"] = "integration_unavailable"
                    else:
                        resource_id = next(
                            (
                                candidate_id
                                for candidate_id, resource in coordinator.data.items()
                                if isinstance(resource, dict)
                                and positive_id(resource.get("account"))
                            ),
                            None,
                        )
                        if resource_id is None:
                            errors["base"] = "account_unavailable"
                        else:
                            assignment = MemberAssignment(
                                async_get_clientsession(self.hass),
                                coordinator,
                                resource_id,
                            )
                            try:
                                resolved_member_id = await assignment.resolve_member(
                                    member_id=member_id,
                                    email_address=email_address,
                                )
                            except ServiceValidationError:
                                errors["base"] = "invalid_member"
                            except (HomeAssistantError, TimeoutError):
                                errors["base"] = "member_lookup_failed"
                            else:
                                mappings = self._mappings()
                                mappings[user_id] = resolved_member_id
                                return self._save_mappings(mappings)

        user_options = {user.id: user.name or user.id for user in users}
        return self.async_show_form(
            step_id="add_mapping",
            data_schema=vol.Schema(
                {
                    vol.Required("ha_user"): vol.In(user_options),
                    vol.Required("fabman_member"): vol.All(
                        str, vol.Length(min=1, max=255)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_mapping(self, user_input=None):
        """Remove one stored user mapping."""
        mappings = self._mappings()
        if not mappings:
            return self.async_abort(reason="no_mappings")

        all_users = await self.hass.auth.async_get_users()
        names = {user.id: user.name or user.id for user in all_users}
        user_options = {
            user_id: f"{names.get(user_id, user_id)} — Fabman {member_id}"
            for user_id, member_id in mappings.items()
        }
        errors = {}
        if user_input is not None:
            user_id = user_input.get("ha_user")
            if user_id not in mappings:
                errors["base"] = "invalid_user"
            else:
                mappings.pop(user_id)
                return self._save_mappings(mappings)

        return self.async_show_form(
            step_id="remove_mapping",
            data_schema=vol.Schema({vol.Required("ha_user"): vol.In(user_options)}),
            errors=errors,
        )

    async def _active_users(self):
        """Return selectable, non-system HA accounts."""
        return [
            user
            for user in await self.hass.auth.async_get_users()
            if user.is_active and not user.system_generated
        ]

    def _mappings(self):
        """Return a copy of the stored mapping after validating its shape."""
        configured = self.config_entry.options.get(CONF_USER_MEMBER_MAP, {})
        if not isinstance(configured, dict):
            return {}
        return {
            user_id: member_id
            for user_id, member_id in configured.items()
            if isinstance(user_id, str) and positive_id(member_id)
        }

    def _save_mappings(self, mappings):
        """Persist the map while retaining any future options."""
        options = dict(self.config_entry.options)
        if mappings:
            options[CONF_USER_MEMBER_MAP] = mappings
        else:
            options.pop(CONF_USER_MEMBER_MAP, None)
        return self.async_create_entry(title="", data=options)
