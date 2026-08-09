# SPDX-License-Identifier: GPL-3.0-or-later
"""Authoritative public identity bridges for Wikimedia and Toolforge."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import requests

from backend import toolhub

try:  # pragma: no cover - production uses ldap3; tests inject a lookup.
    from ldap3 import Connection, Server
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars
except ImportError:  # pragma: no cover - local tests do not require ldap3.
    Connection = None
    Server = None
    escape_filter_chars = None

    class LDAPException(Exception):  # noqa: N818 - mirrors ldap3's public name
        """Fallback exception used when ldap3 is unavailable."""


CENTRALAUTH_API_URL = "https://meta.wikimedia.org/w/api.php"
TOOLFORGE_LDAP_URI = "ldaps://ldap-ro.eqiad.wikimedia.org:636"
TOOLFORGE_LDAP_BASE_DN = "ou=people,dc=wikimedia,dc=org"
TOOLFORGE_LDAP_TIMEOUT = 5
TOOLFORGE_MAX_MEMBERSHIP_TOOLS = 100
HTTP_OK = 200

WikimediaFetcher = Callable[[str], tuple[int, object]]
ToolforgeLookup = Callable[[str], list[Mapping[str, Any]]]


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - external values are untrusted
    return str(value or "").strip()[:limit]


def _first(value: Any) -> Any:  # noqa: ANN401 - ldap3 returns scalar or list-like attributes
    if isinstance(value, (list, tuple)):
        return value[0] if value else ""
    return value


def tool_names_from_member_dns(member_dns: list[Any]) -> tuple[str, ...]:
    """Extract unique Toolforge tool-account names from LDAP memberOf DNs."""
    names: list[str] = []
    for member_dn in member_dns:
        match = re.search(r"(?:^|,)cn=tools\.([^,]+),ou=servicegroups,", str(member_dn), flags=re.IGNORECASE)
        if match and match.group(1).casefold() not in {name.casefold() for name in names}:
            names.append(match.group(1))
    return tuple(names[:TOOLFORGE_MAX_MEMBERSHIP_TOOLS])


@dataclass(frozen=True)
class WikimediaIdentity:
    """One CentralAuth identity resolved by immutable global user id."""

    global_user_id: str
    username: str
    registration: str = ""


@dataclass(frozen=True)
class ToolforgeIdentity:
    """One Toolforge developer identity authoritatively bound through SUL."""

    uid: str
    uid_number: str
    sul_username: str
    tool_names: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedPublicIdentity:
    """Cross-system public identity evidence for one Wikimedia global account."""

    wikimedia: WikimediaIdentity
    toolforge: ToolforgeIdentity | None = None


class WikimediaIdentityProvider:
    """Resolve rename-safe CentralAuth identities through the official API."""

    def __init__(self, fetcher: WikimediaFetcher | None = None) -> None:
        """Allow deterministic provider substitution in tests and offline jobs."""
        self.fetcher = fetcher or self._fetch

    def lookup(self, global_user_id: str) -> WikimediaIdentity | None:
        """Return the exact global identity, rejecting malformed or mismatched rows."""
        expected_id = _clean(global_user_id, 64)
        if not expected_id:
            return None
        try:
            status, payload = self.fetcher(expected_id)
        except (OSError, TimeoutError, ValueError, requests.RequestException):
            return None
        if status != HTTP_OK or not isinstance(payload, dict):
            return None
        query = payload.get("query")
        row = query.get("globaluserinfo") if isinstance(query, dict) else None
        if not isinstance(row, dict):
            return None
        resolved_id = _clean(row.get("id"), 64)
        username = _clean(row.get("name"))
        if resolved_id != expected_id or not username or row.get("missing") is not None:
            return None
        return WikimediaIdentity(
            global_user_id=resolved_id,
            username=username,
            registration=_clean(row.get("registration"), 32),
        )

    @staticmethod
    def _fetch(global_user_id: str) -> tuple[int, object]:
        response = requests.get(
            CENTRALAUTH_API_URL,
            params={
                "action": "query",
                "meta": "globaluserinfo",
                "guiid": global_user_id,
                "format": "json",
                "formatversion": 2,
            },
            headers={"User-Agent": toolhub.USER_AGENT, "Accept": "application/json"},
            timeout=toolhub.REQUEST_TIMEOUT,
        )
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return response.status_code, payload


class ToolforgeIdentityProvider:
    """Resolve a Toolforge developer identity by its authoritative SUL binding."""

    def __init__(self, lookup: ToolforgeLookup | None = None) -> None:
        """Allow an injected LDAP lookup while retaining the production default."""
        self.lookup = lookup or self._lookup_ldap

    def lookup_sul(self, wikimedia_username: str) -> ToolforgeIdentity | None:
        """Return one exact SUL-bound developer account, rejecting ambiguity."""
        expected_sul = _clean(wikimedia_username)
        if not expected_sul:
            return None
        try:
            rows = self.lookup(expected_sul)
        except (LDAPException, OSError, TimeoutError, ValueError):
            return None
        exact = []
        for row in rows:
            sul = _clean(_first(row.get("sul")))
            uid = _clean(_first(row.get("uid")))
            if sul.casefold() != expected_sul.casefold() or not uid:
                continue
            raw_memberships = row.get("memberOf")
            member_dns = list(raw_memberships) if isinstance(raw_memberships, (list, tuple)) else []
            exact.append(
                ToolforgeIdentity(
                    uid=uid,
                    uid_number=_clean(_first(row.get("uidNumber")), 64),
                    sul_username=sul,
                    tool_names=tool_names_from_member_dns(member_dns),
                )
            )
        return exact[0] if len(exact) == 1 else None

    def _lookup_ldap(self, wikimedia_username: str) -> list[Mapping[str, Any]]:
        if Connection is None or Server is None or escape_filter_chars is None:
            return []
        server = Server(TOOLFORGE_LDAP_URI, use_ssl=True, connect_timeout=TOOLFORGE_LDAP_TIMEOUT)
        conn = Connection(server, receive_timeout=TOOLFORGE_LDAP_TIMEOUT, auto_bind=True)
        try:
            conn.search(
                TOOLFORGE_LDAP_BASE_DN,
                f"(sul={escape_filter_chars(wikimedia_username)})",
                attributes=["uid", "uidNumber", "sul", "memberOf"],
                size_limit=2,
            )
            return [dict(entry.entry_attributes_as_dict) for entry in conn.entries]
        finally:
            conn.unbind()


class PublicIdentityResolver:
    """Compose stable Wikimedia identity with optional Toolforge evidence."""

    def __init__(
        self,
        *,
        wikimedia: WikimediaIdentityProvider | None = None,
        toolforge: ToolforgeIdentityProvider | None = None,
    ) -> None:
        """Compose independently replaceable authoritative identity providers."""
        self.wikimedia = wikimedia or WikimediaIdentityProvider()
        self.toolforge = toolforge or ToolforgeIdentityProvider()

    def resolve(self, global_user_id: str) -> ResolvedPublicIdentity | None:
        """Resolve one global id without falling back to mutable display names."""
        wikimedia = self.wikimedia.lookup(global_user_id)
        if wikimedia is None:
            return None
        return ResolvedPublicIdentity(
            wikimedia=wikimedia,
            toolforge=self.toolforge.lookup_sul(wikimedia.username),
        )
