"""Assign only a confirmed, uniquely matched remote activation to a member."""

import asyncio
from datetime import timedelta

import aiohttp
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util


def positive_id(value):
    """Reject booleans and non-integer identifiers."""
    return type(value) is int and 0 < value <= 2147483647


class MemberAssignment:
    """Keep command and usage identity local to one action, never retry activation."""

    def __init__(self, session, coordinator, resource_id):
        self.session = session
        self.coordinator = coordinator
        self.resource_id = resource_id
        self.account = coordinator.data[resource_id].get("account")

    async def request(self, method, path, *, params=None, data=None):
        """Use bounded requests without redirects or sensitive response errors."""
        try:
            async with self.session.request(
                method,
                f"{self.coordinator.api_url.rstrip('/')}/{path}",
                params=params,
                json=data,
                headers={"Authorization": f"Bearer {self.coordinator.api_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise HomeAssistantError(
                        f"Fabman member assignment request failed: HTTP {response.status}"
                    )
                return await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise HomeAssistantError(
                "Fabman member assignment request failed"
            ) from None

    async def resolve_member(self, member_id=None, email_address=None):
        """Resolve an exact member in the resource's account before activation."""
        if member_id is not None and email_address is not None:
            raise ServiceValidationError(
                "Specify either member_id or email_address, not both"
            )
        if not positive_id(self.account):
            raise ServiceValidationError("Fabman resource account is unknown")
        if member_id is not None:
            if not positive_id(member_id):
                raise ServiceValidationError("Invalid Fabman member_id")
            member = await self.request("GET", f"members/{member_id}")
        else:
            if not isinstance(email_address, str) or not email_address.strip():
                raise ServiceValidationError("Invalid Fabman email_address")
            email = email_address.strip().casefold()
            # Fetch at most two results: truncated or ambiguous searches fail closed.
            matches = await self.request(
                "GET",
                "members",
                params={"account": self.account, "q": email, "limit": 2},
            )
            if not isinstance(matches, list) or len(matches) != 1:
                raise ServiceValidationError("Fabman email search is not unique")
            member = matches[0]
            if (
                not isinstance(member, dict)
                or str(member.get("emailAddress", "")).casefold() != email
            ):
                raise ServiceValidationError("No exact Fabman email match")
        if (
            not isinstance(member, dict)
            or not positive_id(member.get("id"))
            or member.get("account") != self.account
            or (member_id is not None and member["id"] != member_id)
        ):
            raise ServiceValidationError(
                "Fabman member does not belong to this account"
            )
        return member["id"]

    def valid_command(self, command, command_id):
        return (
            isinstance(command, dict)
            and positive_id(command_id)
            and command.get("id") == command_id
            and command.get("account") == self.account
            and command.get("resource") == self.resource_id
            and command.get("type") == "activate"
            and positive_id(command.get("member"))
        )

    async def assign(self, command, member_id, baseline_id):
        """Wait for execution, then update one verified log with optimistic locking."""
        command_id = command.get("id") if isinstance(command, dict) else None
        if not self.valid_command(command, command_id):
            raise HomeAssistantError("Invalid Fabman activation acknowledgement")
        async with asyncio.timeout(30):
            while command.get("state") == "pending":
                await asyncio.sleep(1)
                command = await self.request("GET", f"bridge-commands/{command_id}")
                if not self.valid_command(command, command_id):
                    raise HomeAssistantError("Fabman activation identity changed")
            if command.get("state") != "done" or command.get("error"):
                raise HomeAssistantError("Fabman activation was not successful")
            start = self.timestamp(command.get("createdAt"))
            end = self.timestamp(command.get("updatedAt"))
            if (
                start is None
                or end is None
                or end < start
                or end - start > timedelta(seconds=30)
            ):
                raise HomeAssistantError("Invalid Fabman activation time window")
            # Include other users' accesses too: never silently select one of several.
            logs = await self.request(
                "GET",
                "resource-logs",
                params={
                    "resource": self.resource_id,
                    "from": start.isoformat(),
                    "until": end.isoformat(),
                    "type": "allowed",
                    "limit": 2,
                },
            )
            if not isinstance(logs, list) or len(logs) != 1:
                raise HomeAssistantError("No unique Fabman usage for this activation")
            log = logs[0]
            if not self.valid_log(log, command, baseline_id, start, end):
                raise HomeAssistantError("Fabman usage does not match this activation")
            log_id = log["id"]
            # Re-read before changing anything; concurrent changes must not be overwritten.
            current = await self.request("GET", f"resource-logs/{log_id}")
            if (
                not self.valid_log(current, command, baseline_id, start, end)
                or current.get("id") != log_id
            ):
                raise HomeAssistantError("Fabman usage changed before assignment")
            version = current.get("lockVersion")
            if type(version) is not int or version < 0:
                raise HomeAssistantError("Invalid Fabman usage lock version")
            self.coordinator.async_note_assigned_door_grant(self.resource_id, current)
            updated = await self.request(
                "PUT",
                f"resource-logs/{log_id}",
                data={"member": member_id, "lockVersion": version},
            )
            if (
                not isinstance(updated, dict)
                or updated.get("id") != log_id
                or updated.get("member") != member_id
                or updated.get("resource") != self.resource_id
                or updated.get("account") != self.account
            ):
                raise HomeAssistantError(
                    "Fabman member assignment could not be verified"
                )

    @staticmethod
    def timestamp(value):
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        return parsed if parsed is not None and parsed.tzinfo is not None else None

    def valid_log(self, log, command, baseline_id, start, end):
        if not isinstance(log, dict):
            return False
        created = self.timestamp(log.get("createdAt"))
        return (
            positive_id(log.get("id"))
            and log["id"] != baseline_id
            and log.get("resource") == self.resource_id
            and log.get("account") == self.account
            and log.get("type") == "allowed"
            and log.get("member") == command["member"]
            and created is not None
            and start <= created <= end
        )
