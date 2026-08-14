# SPDX-License-Identifier: GPL-3.0-or-later
"""Authoritative public identity bridges for Wikimedia and Toolforge."""

from __future__ import annotations

import re
import time
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
# Wikimedia's published backpressure mechanisms: decline the request when
# replication is lagging, and obey an explicit wait when asked.
MAX_LAG_SECONDS = 5
RATE_LIMIT_STATUSES = frozenset({429, 503})
RATE_LIMIT_RETRIES = 2
MAX_RETRY_DELAY_SECONDS = 30.0
DEFAULT_RETRY_DELAY_SECONDS = 1.0


def retry_delay_seconds(header: str | None) -> float:
    """Return how long a Retry-After header asks us to wait, within bounds."""
    try:
        return min(MAX_RETRY_DELAY_SECONDS, max(0.0, float(header)))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_DELAY_SECONDS


TOOLFORGE_LDAP_URI = "ldaps://ldap-ro.eqiad.wikimedia.org:636"
TOOLFORGE_LDAP_BASE_DN = "ou=people,dc=wikimedia,dc=org"
TOOLFORGE_LDAP_TIMEOUT = 5
TOOLFORGE_MAX_MEMBERSHIP_TOOLS = 100
HTTP_OK = 200

WikimediaFetcher = Callable[[str], tuple[int, object]]
ToolforgeLookup = Callable[[str], list[Mapping[str, Any]]]
ToolforgeSchemaProbe = Callable[[], bool]


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

    def __init__(
        self,
        fetcher: WikimediaFetcher | None = None,
        username_fetcher: WikimediaFetcher | None = None,
    ) -> None:
        """Allow deterministic provider substitution in tests and offline jobs."""
        self.fetcher = fetcher or self._fetch
        self.username_fetcher = username_fetcher or self._fetch_username

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

    def lookup_username(self, username: str) -> WikimediaIdentity | None:
        """Return the global identity a current username resolves to.

        This is the only lookup that starts from text rather than an immutable
        id, so it is the one that can be wrong about *who* is meant: a catalog
        label matching a real account proves the account exists, not that its
        owner wrote the tool. Callers must corroborate before publishing, and
        the shape gate decides which labels are even worth asking about.

        CentralAuth resolves the current name, so the answer is a stable global
        id and later renames do not strand it.
        """
        wanted = _clean(username)
        if not wanted:
            return None
        try:
            status, payload = self.username_fetcher(wanted)
        except (OSError, TimeoutError, ValueError, requests.RequestException):
            return None
        if status != HTTP_OK or not isinstance(payload, dict):
            return None
        query = payload.get("query")
        row = query.get("globaluserinfo") if isinstance(query, dict) else None
        if not isinstance(row, dict) or row.get("missing") is not None:
            return None
        resolved_id = _clean(row.get("id"), 64)
        resolved_name = _clean(row.get("name"))
        if not resolved_id or not resolved_name:
            return None
        return WikimediaIdentity(
            global_user_id=resolved_id,
            username=resolved_name,
            registration=_clean(row.get("registration"), 32),
        )

    @staticmethod
    def _fetch_username(username: str) -> tuple[int, object]:
        """Ask CentralAuth about one username, yielding when it asks us to.

        A fixed delay between requests is a guess about how much load is
        acceptable. These are the mechanisms Wikimedia actually publishes:
        ``maxlag`` declines the request when replication is behind, and a
        429/503 with ``Retry-After`` says how long to wait. Honouring both is
        what makes a faster steady rate reasonable, because the service can
        always push back and be obeyed.
        """
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            response = requests.get(
                CENTRALAUTH_API_URL,
                params={
                    "action": "query",
                    "meta": "globaluserinfo",
                    "guiuser": username,
                    "maxlag": MAX_LAG_SECONDS,
                    "format": "json",
                    "formatversion": 2,
                },
                headers={"User-Agent": toolhub.USER_AGENT, "Accept": "application/json"},
                timeout=toolhub.REQUEST_TIMEOUT,
            )
            if response.status_code not in RATE_LIMIT_STATUSES or attempt == RATE_LIMIT_RETRIES:
                break
            time.sleep(retry_delay_seconds(response.headers.get("Retry-After")))
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return response.status_code, payload

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
    """Resolve a Toolforge developer identity by its immutable Wikimedia binding."""

    def __init__(
        self,
        lookup: ToolforgeLookup | None = None,
        schema_probe: ToolforgeSchemaProbe | None = None,
    ) -> None:
        """Allow an injected LDAP lookup while retaining the production default."""
        self.lookup = lookup or self._lookup_ldap
        self.schema_probe = schema_probe or self._probe_ldap_schema

    def lookup_global(self, global_user_id: str, *, canonical_username: str = "") -> ToolforgeIdentity | None:
        """Return one developer account bound to an immutable global account id."""
        expected_id = _clean(global_user_id, 64)
        if not expected_id:
            return None
        try:
            rows = self.lookup(expected_id)
        except (LDAPException, OSError, TimeoutError, ValueError):
            return None
        exact = []
        for row in rows:
            resolved_id = _clean(_first(row.get("wikimediaGlobalAccountId")), 64)
            linked_username = _clean(_first(row.get("wikimediaGlobalAccountName")))
            uid = _clean(_first(row.get("uid")))
            uid_number = _clean(_first(row.get("uidNumber")), 64)
            if resolved_id != expected_id or not uid or not uid_number:
                continue
            raw_memberships = row.get("memberOf")
            member_dns = list(raw_memberships) if isinstance(raw_memberships, (list, tuple)) else []
            exact.append(
                ToolforgeIdentity(
                    uid=uid,
                    uid_number=uid_number,
                    sul_username=_clean(canonical_username) or linked_username,
                    tool_names=tool_names_from_member_dns(member_dns),
                )
            )
        return exact[0] if len(exact) == 1 else None

    def probe_schema(self) -> bool:
        """Confirm that production LDAP exposes the identity bridge we consume."""
        try:
            return bool(self.schema_probe())
        except (LDAPException, OSError, TimeoutError, ValueError):
            return False

    @staticmethod
    def _ldap_search(ldap_filter: str, *, size_limit: int) -> list[Mapping[str, Any]]:
        if Connection is None or Server is None or escape_filter_chars is None:
            return []
        server = Server(TOOLFORGE_LDAP_URI, use_ssl=True, connect_timeout=TOOLFORGE_LDAP_TIMEOUT)
        conn = Connection(server, receive_timeout=TOOLFORGE_LDAP_TIMEOUT, auto_bind=True)
        try:
            conn.search(
                TOOLFORGE_LDAP_BASE_DN,
                ldap_filter,
                attributes=[
                    "uid",
                    "uidNumber",
                    "wikimediaGlobalAccountId",
                    "wikimediaGlobalAccountName",
                    "memberOf",
                ],
                size_limit=size_limit,
            )
            return [dict(entry.entry_attributes_as_dict) for entry in conn.entries]
        finally:
            conn.unbind()

    def _lookup_ldap(self, global_user_id: str) -> list[Mapping[str, Any]]:
        escaped_id = escape_filter_chars(global_user_id) if escape_filter_chars is not None else ""
        return self._ldap_search(
            f"(&(objectClass=posixAccount)(wikimediaGlobalAccountId={escaped_id}))",
            size_limit=2,
        )

    def _probe_ldap_schema(self) -> bool:
        return bool(
            self._ldap_search(
                "(&(objectClass=posixAccount)(wikimediaGlobalAccountId=*))",
                size_limit=1,
            )
        )


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
            toolforge=self.toolforge.lookup_global(
                wikimedia.global_user_id,
                canonical_username=wikimedia.username,
            ),
        )
