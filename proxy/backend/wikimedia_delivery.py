# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticated Wikimedia Action API publication and delivery helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from backend.http_headers import clean_header_value, clean_secret_header_value
from backend.sync import clean_error
from backend.wikimedia_urls import canonical_username, clean_wiki_domain

DEFAULT_USER_AGENT = "ToolhubDigestBot/1.0 (https://toolhub-evolved.toolforge.org/digests)"
REDACTED = "***"
REQUEST_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
HTTP_BAD_REQUEST = 400
ANONYMOUS_CSRF_TOKEN = "+\\"  # noqa: S105 - public MediaWiki sentinel, not a credential
ERROR_RESPONSE_TOO_LARGE = "response-too-large"
ERROR_TRANSPORT = "transport"
ERROR_CANNOT_SEND = "cantsend"
ERROR_EDIT_FAILED = "edit-failed"
ERROR_EMAIL_FAILED = "email-failed"
ERROR_UNEXPECTED_ACCOUNT = "unexpected-account"
RECIPIENT_ERRORS = {
    "blockedfrommail",
    "cantsend",
    "noemail",
    "nowikiemail",
    "protectedpage",
    "usermaildisabled",
}
# The wiki refused this exact text and will refuse the identical text again, so
# retrying only burns edit attempts. These are content refusals, not recipient
# refusals: the reader is reachable and the subscription stays healthy, so they
# must never suspend a subscription the way RECIPIENT_ERRORS does.
CONTENT_REJECTED_ERRORS = {"spamblacklist"}


class WikimediaAPIError(RuntimeError):
    """One normalized Action API or transport failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        permanent: bool = False,
        recipient_failure: bool | None = None,
    ) -> None:
        """Retain the stable API code and whether retrying can help."""
        super().__init__(clean_error(message))
        self.code = code[:64]
        self.permanent = permanent
        self.recipient_failure = permanent if recipient_failure is None else recipient_failure


@dataclass(frozen=True)
class WikiEditResult:
    """Stable identifiers returned from a successful wiki edit."""

    page_title: str
    revision_id: str
    page_url: str


def api_url(domain: str) -> str:
    """Build a fixed Action API URL after strict host validation."""
    return f"https://{clean_wiki_domain(domain)}/w/api.php"


def page_url(domain: str, title: str) -> str:
    """Build a canonical public page URL for a validated wiki domain."""
    return f"https://{clean_wiki_domain(domain)}/wiki/{quote(title.replace(' ', '_'), safe='/:')}"


class WikimediaClient:
    """Small bearer-authenticated Action API client with per-wiki CSRF caching."""

    def __init__(self, *, access_token: str | None = None, user_agent: str | None = None) -> None:
        """Use explicit test credentials or the Toolforge environment."""
        self.access_token = clean_secret_header_value(
            "WIKIMEDIA_ACCESS_TOKEN",
            access_token if access_token is not None else os.environ.get("WIKIMEDIA_ACCESS_TOKEN", ""),
        )
        self.user_agent = clean_header_value(
            "WIKIMEDIA_USER_AGENT",
            user_agent if user_agent is not None else os.environ.get("WIKIMEDIA_USER_AGENT", DEFAULT_USER_AGENT),
        )
        self.expected_account = canonical_username(os.environ.get("WIKIMEDIA_ACCOUNT_NAME", ""))
        self._csrf: dict[str, str] = {}

    @staticmethod
    def _failure(
        code: str,
        message: str,
        *,
        permanent: bool = False,
        recipient_failure: bool | None = None,
    ) -> WikimediaAPIError:
        return WikimediaAPIError(
            code,
            message,
            permanent=permanent,
            recipient_failure=recipient_failure,
        )

    def _redact(self, text: str) -> str:
        """Strip credential material from a string that will reach a caller.

        Transport exceptions quote what they choked on, and the Authorization
        header is built from the access token, so an exception raised while
        sending it can carry the credential into an API response body and into
        the stored per-subscription last_error. Validation already refuses the
        malformed tokens that trigger that, but the redaction is cheap and the
        disclosure would be permanent.
        """
        return text.replace(self.access_token, REDACTED) if self.access_token else text

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    @staticmethod
    def _error(payload: object, status: int) -> WikimediaAPIError:
        error = payload.get("error") if isinstance(payload, dict) else None
        code = str(error.get("code") or f"http-{status}") if isinstance(error, dict) else f"http-{status}"
        message = str(error.get("info") or error.get("message") or code) if isinstance(error, dict) else code
        recipient_failure = code in RECIPIENT_ERRORS
        return WikimediaAPIError(
            code,
            message,
            permanent=recipient_failure or code in CONTENT_REJECTED_ERRORS,
            recipient_failure=recipient_failure,
        )

    def request(self, domain: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Perform one bounded Action API request and normalize all failures."""
        url = api_url(domain)
        values = {"format": "json", "formatversion": 2, **params}
        try:
            response = requests.request(
                method,
                url,
                params=values if method == "GET" else None,
                data=values if method != "GET" else None,
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise self._failure(ERROR_RESPONSE_TOO_LARGE, "Wikimedia API response exceeded safety limit")
            payload = response.json()
        except WikimediaAPIError:
            raise
        except (OSError, ValueError, requests.RequestException) as exc:
            raise self._failure(ERROR_TRANSPORT, self._redact(str(exc))) from exc
        if response.status_code >= HTTP_BAD_REQUEST or not isinstance(payload, dict) or "error" in payload:
            raise self._error(payload, response.status_code)
        return payload

    def csrf_token(self, domain: str, *, refresh: bool = False) -> str:
        """Return the authenticated account's CSRF token for one wiki."""
        clean_domain = clean_wiki_domain(domain)
        if not refresh and clean_domain in self._csrf:
            return self._csrf[clean_domain]
        payload = self.request(
            clean_domain,
            "GET",
            {"action": "query", "meta": "tokens|userinfo", "type": "csrf", "uiprop": "groups"},
        )
        query = payload.get("query")
        userinfo = query.get("userinfo") if isinstance(query, dict) else None
        authenticated_name = str(userinfo.get("name") or "") if isinstance(userinfo, dict) else ""
        if self.expected_account and canonical_username(authenticated_name) != self.expected_account:
            raise self._failure(
                ERROR_UNEXPECTED_ACCOUNT,
                f"Wikimedia token belongs to {authenticated_name or 'an unknown account'}, not the configured account",
                permanent=True,
                recipient_failure=False,
            )
        tokens = query.get("tokens") if isinstance(query, dict) else None
        token = str(tokens.get("csrftoken") or "") if isinstance(tokens, dict) else ""
        if not token or token == ANONYMOUS_CSRF_TOKEN:
            raise self._failure(
                ERROR_CANNOT_SEND,
                "Wikimedia service account authentication is unavailable",
                permanent=True,
                recipient_failure=False,
            )
        self._csrf[clean_domain] = token
        return token

    def page_source(self, domain: str, title: str) -> tuple[str, str]:
        """Return current wikitext and revision id, or empty values for a missing page."""
        payload = self.request(
            domain,
            "GET",
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "ids|content",
                "rvslots": "main",
                "titles": title,
            },
        )
        query = payload.get("query")
        pages = query.get("pages") if isinstance(query, dict) else None
        page = pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], dict) else {}
        revisions = page.get("revisions")
        revision = revisions[0] if isinstance(revisions, list) and revisions and isinstance(revisions[0], dict) else {}
        slots = revision.get("slots")
        main = slots.get("main") if isinstance(slots, dict) else None
        content = str(main.get("content") or "") if isinstance(main, dict) else ""
        return content, str(revision.get("revid") or "")

    def user_exists(self, domain: str, username: str) -> bool:
        """Return whether the canonical global username is attached on this wiki."""
        return self.user_identity_matches(domain, username)

    def user_identity_matches(self, domain: str, username: str, global_user_id: str = "") -> bool:
        """Verify a local account and, when supplied, its stable CentralAuth id."""
        clean_username = username.strip()
        if not clean_username:
            return False
        payload = self.request(
            domain,
            "GET",
            {
                "action": "query",
                "list": "users",
                "ususers": clean_username,
                "usprop": "centralids",
            },
        )
        query = payload.get("query")
        users = query.get("users") if isinstance(query, dict) else None
        row = users[0] if isinstance(users, list) and users and isinstance(users[0], dict) else {}
        exists = row.get("missing") is None and row.get("invalid") is None and bool(str(row.get("name") or ""))
        expected_id = global_user_id.strip()
        if not exists or not expected_id:
            return exists
        central_ids = row.get("centralids")
        return isinstance(central_ids, dict) and str(central_ids.get("CentralAuth") or "") == expected_id

    def _csrf_post(self, domain: str, params: dict[str, Any]) -> dict[str, Any]:
        """Perform an authenticated write and retry once after CSRF expiry."""
        values = {"assert": "user", **params, "token": self.csrf_token(domain)}
        try:
            return self.request(domain, "POST", values)
        except WikimediaAPIError as exc:
            if exc.code != "badtoken":
                raise
            values["token"] = self.csrf_token(domain, refresh=True)
            return self.request(domain, "POST", values)

    def edit_page(  # noqa: PLR0913 - Action API edit controls are independently meaningful
        self,
        domain: str,
        title: str,
        text: str,
        *,
        summary: str,
        create_only: bool = False,
        base_revision_id: str = "",
    ) -> WikiEditResult:
        """Create or replace one page with conflict-aware, bot-marked editing."""
        params: dict[str, Any] = {
            "action": "edit",
            "title": title,
            "text": text,
            "summary": summary,
            "bot": 1,
        }
        if create_only:
            params["createonly"] = 1
        if base_revision_id:
            params["baserevid"] = base_revision_id
        payload = self._csrf_post(domain, params)
        edit = payload.get("edit")
        if not isinstance(edit, dict) or str(edit.get("result") or "").casefold() != "success":
            raise self._failure(ERROR_EDIT_FAILED, "Wikimedia edit did not report success")
        return WikiEditResult(title, str(edit.get("newrevid") or edit.get("oldrevid") or ""), page_url(domain, title))

    def append_talk_section(self, domain: str, username: str, title: str, text: str, marker: str) -> WikiEditResult:
        """Append one section unless its immutable edition marker already exists."""
        page_title = f"User talk:{username.strip()}"
        source, revision_id = self.page_source(domain, page_title)
        if marker in source:
            return WikiEditResult(page_title, revision_id, page_url(domain, page_title))
        params = {
            "action": "edit",
            "title": page_title,
            "section": "new",
            "sectiontitle": title,
            "text": text,
            "summary": f"Deliver {title} subscription",
            "bot": 1,
        }
        if revision_id:
            params["baserevid"] = revision_id
        payload = self._csrf_post(domain, params)
        edit = payload.get("edit")
        if not isinstance(edit, dict) or str(edit.get("result") or "").casefold() != "success":
            raise self._failure(ERROR_EDIT_FAILED, "Talk-page delivery did not report success")
        return WikiEditResult(page_title, str(edit.get("newrevid") or ""), page_url(domain, page_title))

    def email_user(self, domain: str, username: str, subject: str, text: str) -> str:
        """Send one plaintext message through MediaWiki's privacy-preserving emailuser action."""
        params = {
            "action": "emailuser",
            "target": username.strip(),
            "subject": subject[:500],
            "text": text,
        }
        payload = self._csrf_post(domain, params)
        outcome = payload.get("emailuser")
        if not isinstance(outcome, dict) or str(outcome.get("result") or "").casefold() != "success":
            raise self._failure(ERROR_EMAIL_FAILED, "Wikimedia email did not report success")
        return "success"
