# SPDX-License-Identifier: GPL-3.0-or-later
"""Author-claim verification providers for the hybrid Toolhub/Evolved model."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from html import unescape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urlparse

import requests
from sqlalchemy import and_, or_, select

from backend import canonical_tools, toolhub, toolinfo_authors
from backend.models import ToolAuthorClaim, ToolAuthorKey, User, utcnow
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_FAILED,
    AUTHOR_CLAIM_REVOKED,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_STALE,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_UNVERIFIED,
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
    PERSON_REL_RECORD_OWNER,
    clean_author_claim_method,
    clean_author_claim_status,
    clean_error,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

try:  # pragma: no cover - exercised in production when the optional dependency is installed.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
except ImportError:  # pragma: no cover - local tests inject a verifier and do not require cryptography.
    Ed25519PublicKey = None
    load_pem_public_key = None

TOOLFORGE_BASE_URL = "https://toolsadmin.wikimedia.org"
TOOLFORGE_TIMEOUT = 5
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
TOOLFORGE_CLAIM_TTL = timedelta(days=1)
DISPLAY_NAME_CLAIM_TTL = timedelta(days=30)
WRITE_CLAIM_TTL = timedelta(days=30)
SIGNED_CLAIM_TTL = timedelta(days=90)
MAX_EVIDENCE_URL = 2000
MAX_SIGNATURE_PREFIX = 32
ED25519_RAW_PUBLIC_KEY_BYTES = 32
OFFICIAL_WRITE_MIN_PARTS = 2
OFFICIAL_WRITE_DETAIL_PARTS = 3
SIGNATURE_META_KEYS = ("x_toolhub_evolved_signature", "x-toolhub-evolved-signature")
SIGNATURE_META_KEY = SIGNATURE_META_KEYS[0]
AUTHOR_CLAIM_STRONG_METHODS = {
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
}

SignatureVerifier = Callable[[str, bytes, bytes], None]
ToolforgeFetcher = Callable[[str], tuple[int, str]]


@dataclass(frozen=True)
class SignatureMeta:
    """Normalized signed-toolinfo metadata."""

    algorithm: str
    key_id: str
    signature: str


@dataclass(frozen=True)
class ToolsadminMaintainer:
    """One maintainer listed by the public Toolsadmin page."""

    display_name: str
    username: str = ""


class _MaintainerParser(HTMLParser):
    """Extract Toolsadmin maintainer names from public tool pages."""

    def __init__(self) -> None:
        super().__init__()
        self._in_anchor = False
        self._href = ""
        self._username = ""
        self.entries: list[ToolsadminMaintainer] = []
        self.maintainers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._href = dict(attrs).get("href") or ""
        self._in_anchor = "/profile/" in self._href or "/users/" in self._href
        self._username = _toolsadmin_username_from_href(self._href) if self._in_anchor else ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_anchor = False
            self._href = ""
            self._username = ""

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            name = clean_string(data)
            if name:
                self.maintainers.append(name)
                self.entries.append(ToolsadminMaintainer(display_name=name, username=self._username))


def clean_string(value: Any) -> str:  # noqa: ANN401 - untrusted API/user JSON
    """Return a stripped string value."""
    return str(value).strip() if value is not None else ""


def string_key(value: Any) -> str:  # noqa: ANN401 - untrusted API/user JSON
    """Return a case-insensitive comparison key."""
    return clean_string(value).casefold()


def _toolsadmin_username_from_href(href: str) -> str:
    """Extract a stable profile handle from a Toolsadmin maintainer link."""
    parts = [unquote(part).strip() for part in urlparse(href).path.split("/") if part.strip()]
    for marker in ("profile", "users"):
        if marker in parts:
            index = parts.index(marker) + 1
            if index < len(parts):
                return parts[index][:255]
    return ""


def dedupe_strings(values: list[Any]) -> list[str]:
    """Return non-empty strings in first-seen order, case-insensitively deduped."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_string(value)
        key = text.casefold()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def author_names_from_toolhub_tool(tool: dict) -> list[str]:
    """Return declared author display and identity names from one official Toolhub tool."""
    return toolinfo_authors.author_names(tool)


def author_names_from_toolinfo(toolinfo: dict) -> list[str]:
    """Return author names from a toolinfo.json item."""
    return toolinfo_authors.author_names(toolinfo)


def claim_is_verified(status: str, method: str, *, expires_at: Any = None) -> bool:  # noqa: ANN401
    """Return true only for fresh, strong Evolved-local verification methods."""
    return status == AUTHOR_CLAIM_VERIFIED and method in AUTHOR_CLAIM_STRONG_METHODS and not _is_expired(expires_at)


def claim_payload(row: ToolAuthorClaim) -> dict:
    """Serialize one stored author claim into the resolver response contract."""
    status = AUTHOR_CLAIM_REVOKED if row.revoked_at is not None else clean_author_claim_status(row.verification_status)
    method = clean_author_claim_method(row.verification_method)
    if status == AUTHOR_CLAIM_VERIFIED and _is_expired(row.expires_at):
        status = AUTHOR_CLAIM_STALE
    return {
        "id": row.id,
        "toolName": row.tool_name,
        "authorName": row.author_name,
        "toolhubUsername": row.toolhub_username,
        "verificationStatus": status,
        "verificationMethod": method,
        "requestedRelationship": claim_relationship_for_method(method),
        "isVerified": claim_is_verified(status, method, expires_at=row.expires_at),
        "evidenceUrl": row.evidence_url or "",
        "evidencePayload": row.evidence_payload,
        "checkedAt": _iso(row.checked_at),
        "expiresAt": _iso(row.expires_at),
        "lastError": row.last_error or "",
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
        "revokedAt": _iso(row.revoked_at),
    }


def claim_relationship_for_method(method: str) -> str:
    """Return the relationship a proof method is allowed to establish."""
    clean_method = clean_author_claim_method(method)
    if clean_method == AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS:
        return PERSON_REL_RECORD_OWNER
    if clean_method == AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME:
        return PERSON_REL_AUTHOR
    return PERSON_REL_MAINTAINER


def record_author_claim(  # noqa: PLR0913 - claim rows intentionally carry explicit evidence fields
    s: Session,
    *,
    tool_name: str,
    author_name: str,
    toolhub_username: str,
    verification_status: str,
    verification_method: str,
    user_id: int | None = None,
    evidence_url: str | None = None,
    evidence_payload: dict | None = None,
    expires_at: Any = None,  # noqa: ANN401
    last_error: str | None = None,
) -> ToolAuthorClaim:
    """Upsert one author claim by its provider-specific uniqueness tuple."""
    method = clean_author_claim_method(verification_method)
    status = clean_author_claim_status(verification_status)
    if method == AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME and status == AUTHOR_CLAIM_VERIFIED:
        status = AUTHOR_CLAIM_UNVERIFIED
    identity = and_(
        ToolAuthorClaim.tool_name == clean_string(tool_name),
        ToolAuthorClaim.author_name == clean_string(author_name),
        ToolAuthorClaim.verification_method == method,
    )
    account = (
        or_(
            ToolAuthorClaim.user_id == user_id,
            and_(
                ToolAuthorClaim.user_id.is_(None),
                ToolAuthorClaim.toolhub_username == clean_string(toolhub_username),
            ),
        )
        if user_id is not None
        else ToolAuthorClaim.toolhub_username == clean_string(toolhub_username)
    )
    row = s.execute(select(ToolAuthorClaim).where(identity, account)).scalar_one_or_none()
    if row is None:
        row = ToolAuthorClaim(
            tool_name=clean_string(tool_name),
            author_name=clean_string(author_name),
            toolhub_username=clean_string(toolhub_username),
            verification_method=method,
        )
        s.add(row)
    row.user_id = user_id or row.user_id
    row.toolhub_username = clean_string(toolhub_username)
    row.verification_status = status
    row.requested_relationship = claim_relationship_for_method(method)
    row.revoked_at = None
    row.evidence_url = (evidence_url or "")[:MAX_EVIDENCE_URL] or None
    row.evidence_payload = evidence_payload
    row.checked_at = utcnow()
    row.expires_at = expires_at
    row.last_error = clean_error(last_error)
    row.updated_at = utcnow()
    return row


class AuthorNameProvider:
    """Persist display-name-only candidate matches as unverified claims."""

    def record(  # noqa: PLR0913 - provider calls keep claim evidence fields explicit.
        self,
        s: Session,
        user: User,
        *,
        tool_name: str,
        author_names: list[str],
        evidence_url: str,
        evidence_payload: dict | None = None,
    ) -> list[ToolAuthorClaim]:
        """Record unverified display-name claims for one Toolhub search result."""
        expires_at = utcnow() + DISPLAY_NAME_CLAIM_TTL
        return [
            record_author_claim(
                s,
                tool_name=tool_name,
                author_name=author_name,
                toolhub_username=user.username,
                user_id=user.id,
                verification_status=AUTHOR_CLAIM_UNVERIFIED,
                verification_method=AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                evidence_url=evidence_url,
                evidence_payload=evidence_payload,
                expires_at=expires_at,
            )
            for author_name in dedupe_strings(author_names)
        ]


class ToolforgeMaintainerProvider:
    """Verify a candidate through the public Toolsadmin maintainer list."""

    def __init__(self, *, base_url: str = TOOLFORGE_BASE_URL, fetcher: ToolforgeFetcher | None = None) -> None:
        """Store the public Toolsadmin base URL and optional test fetcher."""
        self.base_url = base_url.rstrip("/")
        self.fetcher = fetcher or self._fetch

    def verify(
        self,
        s: Session,
        user: User,
        *,
        tool_name: str,
        author_names: list[str],
        toolhub_tool: dict | None = None,
    ) -> list[ToolAuthorClaim]:
        """Record verified/failed claims from Toolsadmin maintainer evidence."""
        toolforge_names = toolforge_names_from_toolhub_tool(tool_name, toolhub_tool or {})
        if not toolforge_names:
            return []
        names = dedupe_strings(author_names) or [user.username]
        fresh_rows = self._fresh_rows(s, user, tool_name, names)
        if len(fresh_rows) == len(names):
            return fresh_rows
        for toolforge_name in toolforge_names:
            evidence_url = self.evidence_url(toolforge_name)
            try:
                status, body = self.fetcher(toolforge_name)
            except requests.RequestException as exc:
                return self._record_failed(s, user, tool_name, names, evidence_url, str(exc))
            if status == HTTP_NOT_FOUND:
                continue
            if status >= HTTP_BAD_REQUEST:
                return self._record_failed(s, user, tool_name, names, evidence_url, f"Toolsadmin returned {status}")
            maintainer_entries = parse_toolsadmin_maintainer_entries(body)
            if any(
                string_key(entry.username) == string_key(user.username)
                or string_key(entry.display_name) == string_key(user.username)
                for entry in maintainer_entries
            ):
                return self._record_verified(
                    s, user, tool_name, names, toolforge_name, maintainer_entries, evidence_url
                )
        return self._record_failed(
            s,
            user,
            tool_name,
            names,
            self.evidence_url(toolforge_names[0]),
            "user is not listed as a Toolforge maintainer",
        )

    def record_membership(
        self,
        s: Session,
        user: User,
        *,
        tool_name: str,
        toolforge_name: str,
        toolforge_username: str,
    ) -> ToolAuthorClaim:
        """Record direct LDAP membership without requiring a page fetch.

        LDAP membership is returned for the authenticated Wikimedia identity and
        names the exact ``tools.<account>`` service group. It is therefore a
        stronger account-access proof than matching a canonical author string;
        Toolsadmin remains the public catalog-wide maintainer source.
        """
        return record_author_claim(
            s,
            tool_name=tool_name,
            author_name=user.username,
            toolhub_username=user.username,
            user_id=user.id,
            verification_status=AUTHOR_CLAIM_VERIFIED,
            verification_method=AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
            evidence_url=self.evidence_url(toolforge_name),
            evidence_payload={
                "toolforgeToolName": toolforge_name,
                "toolforgeUsername": clean_string(toolforge_username),
                "ldapServiceGroup": f"tools.{toolforge_name}",
                "discoveryMethod": "toolforge_ldap_membership",
            },
            expires_at=utcnow() + TOOLFORGE_CLAIM_TTL,
        )

    def evidence_url(self, toolforge_name: str) -> str:
        """Return the public Toolsadmin page used as evidence."""
        return f"{self.base_url}/tools/id/{quote(toolforge_name, safe='')}"

    def _fetch(self, toolforge_name: str) -> tuple[int, str]:
        response = requests.get(
            self.evidence_url(toolforge_name),
            headers={"User-Agent": toolhub.USER_AGENT, "Accept": "text/html"},
            timeout=TOOLFORGE_TIMEOUT,
        )
        return response.status_code, response.text

    def _fresh_rows(self, s: Session, user: User, tool_name: str, author_names: list[str]) -> list[ToolAuthorClaim]:
        """Return fresh verified rows in the requested author-name order."""
        rows = s.execute(
            select(ToolAuthorClaim).where(
                ToolAuthorClaim.tool_name == tool_name,
                or_(
                    ToolAuthorClaim.user_id == user.id,
                    and_(
                        ToolAuthorClaim.user_id.is_(None),
                        ToolAuthorClaim.toolhub_username == user.username,
                    ),
                ),
                ToolAuthorClaim.verification_method == AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                ToolAuthorClaim.verification_status == AUTHOR_CLAIM_VERIFIED,
            )
        ).scalars()
        fresh = {string_key(row.author_name): row for row in rows if not _is_expired(row.expires_at)}
        return [fresh[key] for name in author_names if (key := string_key(name)) in fresh]

    def _record_verified(  # noqa: PLR0913 - claim evidence is clearer as named arguments.
        self,
        s: Session,
        user: User,
        tool_name: str,
        author_names: list[str],
        toolforge_name: str,
        maintainers: list[ToolsadminMaintainer],
        evidence_url: str,
    ) -> list[ToolAuthorClaim]:
        expires_at = utcnow() + TOOLFORGE_CLAIM_TTL
        return [
            record_author_claim(
                s,
                tool_name=tool_name,
                author_name=author_name,
                toolhub_username=user.username,
                user_id=user.id,
                verification_status=AUTHOR_CLAIM_VERIFIED,
                verification_method=AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                evidence_url=evidence_url,
                evidence_payload={
                    "toolforgeToolName": toolforge_name,
                    "maintainers": [
                        {"displayName": entry.display_name, "username": entry.username} for entry in maintainers
                    ],
                },
                expires_at=expires_at,
            )
            for author_name in author_names
        ]

    def _record_failed(  # noqa: PLR0913 - claim evidence is clearer as named arguments.
        self,
        s: Session,
        user: User,
        tool_name: str,
        author_names: list[str],
        evidence_url: str,
        last_error: str,
    ) -> list[ToolAuthorClaim]:
        expires_at = utcnow() + TOOLFORGE_CLAIM_TTL
        return [
            record_author_claim(
                s,
                tool_name=tool_name,
                author_name=author_name,
                toolhub_username=user.username,
                user_id=user.id,
                verification_status=AUTHOR_CLAIM_FAILED,
                verification_method=AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                evidence_url=evidence_url,
                evidence_payload=None,
                expires_at=expires_at,
                last_error=last_error,
            )
            for author_name in author_names
        ]


class ToolhubWriteProvider:
    """Verify a Toolhub user after a successful official write to a tool."""

    def record_success(  # noqa: PLR0913 - official write evidence needs request and response payloads.
        self,
        s: Session,
        user: User,
        *,
        method: str,
        path: str,
        request_payload: object | None,
        response_payload: object | None,
    ) -> list[ToolAuthorClaim]:
        """Record write-access claims for official Toolhub tool writes."""
        tool_name = tool_name_from_official_write(path, request_payload, response_payload)
        if tool_name is None:
            return []
        author_names = author_names_from_payloads(response_payload, request_payload) or [user.username]
        expires_at = utcnow() + WRITE_CLAIM_TTL
        return [
            record_author_claim(
                s,
                tool_name=tool_name,
                author_name=author_name,
                toolhub_username=user.username,
                user_id=user.id,
                verification_status=AUTHOR_CLAIM_VERIFIED,
                verification_method=AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
                evidence_url=f"{toolhub.base_url()}/api/tools/{quote(tool_name, safe='')}/",
                evidence_payload={"method": method, "path": path},
                expires_at=expires_at,
            )
            for author_name in author_names
        ]


class SignedToolinfoProvider:
    """Verify signed toolinfo.json records against Evolved-registered public keys."""

    def __init__(self, verifier: SignatureVerifier | None = None) -> None:
        """Store the signature verifier, injectable for deterministic tests."""
        self.verifier = verifier or verify_ed25519_signature

    def verify(
        self,
        s: Session,
        user: User,
        *,
        toolinfo: dict,
        evidence_url: str | None = None,
    ) -> list[ToolAuthorClaim]:
        """Record signed-toolinfo claims for one toolinfo item when signature metadata is present."""
        tool_name = clean_string(toolinfo.get("name"))
        signature = signature_meta(toolinfo)
        if not tool_name or signature is None:
            return []
        author_names = author_names_from_toolinfo(toolinfo) or [user.username]
        if signature.algorithm != "ed25519":
            return self._record_failure(
                s,
                user,
                tool_name,
                author_names,
                evidence_url,
                signature,
                "unsupported signature algorithm",
            )
        key = self._key_for_signature(s, user, signature)
        if key is None:
            return self._record_failure(
                s,
                user,
                tool_name,
                author_names,
                evidence_url,
                signature,
                "public key not found",
            )
        try:
            self.verifier(
                key.public_key,
                base64.b64decode(signature.signature, validate=True),
                canonical_toolinfo_bytes(toolinfo),
            )
        except (binascii.Error, TypeError, ValueError, RuntimeError) as exc:
            return self._record_failure(s, user, tool_name, author_names, evidence_url, signature, str(exc))
        key.last_used_at = utcnow()
        expires_at = utcnow() + SIGNED_CLAIM_TTL
        return [
            record_author_claim(
                s,
                tool_name=tool_name,
                author_name=author_name,
                toolhub_username=user.username,
                user_id=user.id,
                verification_status=AUTHOR_CLAIM_VERIFIED,
                verification_method=AUTHOR_CLAIM_SIGNED_TOOLINFO,
                evidence_url=evidence_url,
                evidence_payload={
                    "algorithm": signature.algorithm,
                    "keyId": signature.key_id,
                    "signaturePrefix": signature.signature[:MAX_SIGNATURE_PREFIX],
                },
                expires_at=expires_at,
            )
            for author_name in author_names
        ]

    def _key_for_signature(self, s: Session, user: User, signature: SignatureMeta) -> ToolAuthorKey | None:
        key = s.execute(
            select(ToolAuthorKey).where(
                or_(
                    ToolAuthorKey.user_id == user.id,
                    and_(ToolAuthorKey.user_id.is_(None), ToolAuthorKey.toolhub_username == user.username),
                ),
                ToolAuthorKey.key_id == signature.key_id,
                ToolAuthorKey.algorithm == signature.algorithm,
                ToolAuthorKey.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        if key is not None:
            # Opportunistically migrate legacy username-owned keys on use.
            key.user_id = user.id
            key.toolhub_username = user.username
        return key

    def _record_failure(  # noqa: PLR0913 - claim evidence is clearer as named arguments.
        self,
        s: Session,
        user: User,
        tool_name: str,
        author_names: list[str],
        evidence_url: str | None,
        signature: SignatureMeta,
        last_error: str,
    ) -> list[ToolAuthorClaim]:
        expires_at = utcnow() + SIGNED_CLAIM_TTL
        return [
            record_author_claim(
                s,
                tool_name=tool_name,
                author_name=author_name,
                toolhub_username=user.username,
                user_id=user.id,
                verification_status=AUTHOR_CLAIM_FAILED,
                verification_method=AUTHOR_CLAIM_SIGNED_TOOLINFO,
                evidence_url=evidence_url,
                evidence_payload={"algorithm": signature.algorithm, "keyId": signature.key_id},
                expires_at=expires_at,
                last_error=last_error,
            )
            for author_name in author_names
        ]


def _html_fragment_text(fragment: str) -> str:
    """Return normalized visible-ish text from a small HTML fragment."""
    text = re.sub(r"<[^>]+>", " ", unescape(fragment))
    return clean_string(re.sub(r"\s+", " ", text))


def _dedupe_toolsadmin_maintainers(entries: list[ToolsadminMaintainer]) -> list[ToolsadminMaintainer]:
    """Deduplicate maintainer entries by stable handle, then display name."""
    out: list[ToolsadminMaintainer] = []
    seen: set[str] = set()
    for entry in entries:
        display_name = clean_string(entry.display_name)
        username = clean_string(entry.username)
        key = string_key(username or display_name)
        if display_name and key and key not in seen:
            out.append(ToolsadminMaintainer(display_name=display_name, username=username))
            seen.add(key)
    return out


def parse_toolsadmin_maintainer_entries(html: str) -> list[ToolsadminMaintainer]:
    """Extract maintainer display names and stable profile handles."""
    entries: list[ToolsadminMaintainer] = []
    found_captioned_table = False
    for table in re.findall(r"<table\b[^>]*>.*?</table>", html, flags=re.DOTALL | re.IGNORECASE):
        caption_match = re.search(r"<caption[^>]*>(.*?)</caption>", table, flags=re.DOTALL | re.IGNORECASE)
        if caption_match is None or string_key(_html_fragment_text(caption_match.group(1))) != "maintainers":
            continue
        found_captioned_table = True
        parser = _MaintainerParser()
        parser.feed(table)
        entries.extend(parser.entries)
        if not parser.entries:
            entries.extend(
                ToolsadminMaintainer(display_name=_html_fragment_text(cell))
                for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", table, flags=re.DOTALL | re.IGNORECASE)
            )
    if found_captioned_table:
        return _dedupe_toolsadmin_maintainers(entries)

    parser = _MaintainerParser()
    parser.feed(html)
    if parser.entries:
        return _dedupe_toolsadmin_maintainers(parser.entries)
    marker = re.search(r"Maintainers\s+Maintainers\s+(.*?)\s+Git repositories", html, flags=re.DOTALL | re.IGNORECASE)
    if marker is None:
        return []
    return _dedupe_toolsadmin_maintainers(
        [ToolsadminMaintainer(display_name=line.strip()) for line in marker.group(1).splitlines()]
    )


def parse_toolsadmin_maintainers(html: str) -> list[str]:
    """Extract public maintainer names from a Toolsadmin tool detail page."""
    return [entry.display_name for entry in parse_toolsadmin_maintainer_entries(html)]


def toolforge_names_from_toolhub_tool(tool_name: str, tool: dict) -> list[str]:
    """Compatibility wrapper for canonical Toolforge project inference."""
    return canonical_tools.toolforge_project_names(tool_name, tool)


def tool_name_from_official_write(
    path: str,
    request_payload: object | None,
    response_payload: object | None,
) -> str | None:
    """Return the Toolhub tool name affected by an official write path."""
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) < OFFICIAL_WRITE_MIN_PARTS or parts[0] != "api" or parts[1] != "tools":
        return None
    response_name = _dict_string(response_payload, "name")
    request_name = _dict_string(request_payload, "name")
    if len(parts) >= OFFICIAL_WRITE_DETAIL_PARTS:
        return clean_string(parts[2])
    return clean_string(response_name or request_name) or None


def author_names_from_payloads(*payloads: object | None) -> list[str]:
    """Return author names from the first Toolhub/toolinfo-like payload that has them."""
    for payload in payloads:
        if isinstance(payload, dict):
            names = author_names_from_toolhub_tool(payload)
            if names:
                return names
    return []


def canonical_toolinfo_bytes(toolinfo: dict) -> bytes:
    """Return canonical signed bytes for a toolinfo item without signature metadata."""
    clean = deepcopy(toolinfo)
    for key in SIGNATURE_META_KEYS:
        clean.pop(key, None)
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_toolinfo_string(toolinfo: dict) -> str:
    """Return canonical signed JSON as UTF-8 text for the Developer settings UI."""
    return canonical_toolinfo_bytes(toolinfo).decode("utf-8")


def signature_meta(toolinfo: dict) -> SignatureMeta | None:
    """Return normalized signature metadata from a toolinfo item."""
    raw = next((toolinfo.get(key) for key in SIGNATURE_META_KEYS if isinstance(toolinfo.get(key), dict)), None)
    if raw is None:
        return None
    algorithm = clean_string(raw.get("algorithm") or "ed25519").lower()
    key_id = clean_string(raw.get("key_id") or raw.get("keyId"))
    signature = clean_string(raw.get("signature"))
    if not key_id or not signature:
        return None
    return SignatureMeta(algorithm=algorithm, key_id=key_id, signature=signature)


def public_key_fingerprint(public_key: str) -> str:
    """Return a stable short fingerprint for a registered public key."""
    digest = hashlib.sha256(clean_string(public_key).encode("utf-8")).hexdigest()
    return f"SHA256:{digest[:16]}"


def validate_ed25519_public_key(public_key: str) -> str:
    """Return a clean Ed25519 public key or raise ValueError when it is unusable."""
    text = clean_string(public_key)
    if not text:
        msg = "public key is required"
        raise ValueError(msg)
    if "PRIVATE KEY" in text.upper():
        msg = "register a public key, not a private key"
        raise ValueError(msg)
    if text.startswith("-----BEGIN"):
        if "PUBLIC KEY" not in text.upper():
            msg = "public key PEM must contain a PUBLIC KEY block"
            raise ValueError(msg)
        if Ed25519PublicKey is not None and load_pem_public_key is not None:  # pragma: no cover
            _load_ed25519_public_key(text)  # pragma: no cover
        return text
    try:
        raw = base64.b64decode(text, validate=True)
    except binascii.Error as exc:
        msg = "public key must be PEM or base64 raw Ed25519 bytes"
        raise ValueError(msg) from exc
    if len(raw) != ED25519_RAW_PUBLIC_KEY_BYTES:
        msg = "base64 raw Ed25519 public keys must decode to 32 bytes"
        raise ValueError(msg)
    if Ed25519PublicKey is not None:  # pragma: no cover
        _load_ed25519_public_key(text)  # pragma: no cover
    return text


def verify_ed25519_signature(public_key: str, signature: bytes, message: bytes) -> None:  # pragma: no cover
    """Verify an Ed25519 signature using cryptography when installed."""
    if Ed25519PublicKey is None or load_pem_public_key is None:
        msg = "cryptography package is required for signed_toolinfo verification"
        raise RuntimeError(msg)
    key = _load_ed25519_public_key(public_key)
    key.verify(signature, message)


def _load_ed25519_public_key(public_key: str) -> Ed25519PublicKey:  # pragma: no cover
    key_text = public_key.strip()
    if key_text.startswith("-----BEGIN"):
        key = load_pem_public_key(key_text.encode("utf-8"))
    else:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_text))
    if not isinstance(key, Ed25519PublicKey):
        msg = "public key is not an Ed25519 key"
        raise TypeError(msg)
    return key


def _dict_string(payload: object | None, key: str) -> str:
    if isinstance(payload, dict):
        return clean_string(payload.get(key))
    return ""


def _iso(value: Any) -> str:  # noqa: ANN401
    return value.isoformat(timespec="seconds") + "Z" if value else ""


def _is_expired(value: Any) -> bool:  # noqa: ANN401
    return value is not None and value <= utcnow()
