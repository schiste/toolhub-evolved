# SPDX-License-Identifier: GPL-3.0-or-later
"""Official Toolhub OAuth and API client helpers.

Toolhub Evolved never exposes official Toolhub access tokens to the browser.
The browser writes to our CSRF-protected /v1 endpoints; those endpoints use the
per-user grant stored here to call the official Toolhub API.
"""

import os
from datetime import UTC, datetime, timedelta
from json import dumps, loads
from urllib.parse import urlencode

import requests
from sqlalchemy import select

from backend import api_cache, db, token_crypto
from backend.models import ToolhubToken, utcnow

DEFAULT_BASE_URL = "https://toolhub.wikimedia.org"
REQUEST_TIMEOUT = 20
TOKEN_REFRESH_SKEW_SECONDS = 60
SCOPES = "read write"
HTTP_NO_CONTENT = 204
USER_AGENT = "toolhub-evolved/0.2 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
_CACHEABLE_MIN_STATUS = 200
_CACHEABLE_MAX_STATUS = 300


class ToolhubAuthError(RuntimeError):
    """Raised when the current user has no usable official Toolhub grant."""


class ToolhubAPIError(RuntimeError):
    """Official Toolhub rejected or failed a request."""

    def __init__(self, status_code: int, payload: object) -> None:
        """Store upstream response details for the caller."""
        super().__init__(f"Toolhub API returned {status_code}")
        self.status_code = status_code
        self.payload = payload


def base_url() -> str:
    """Return the official Toolhub base URL, overridable for tests/staging."""
    return os.environ.get("TOOLHUB_API_BASE", DEFAULT_BASE_URL).rstrip("/")


def oauth_client() -> tuple[str, str] | None:
    """Return the OAuth client id/secret configured for official Toolhub."""
    cid = os.environ.get("TOOLHUB_OAUTH_CLIENT_ID", "")
    secret = os.environ.get("TOOLHUB_OAUTH_CLIENT_SECRET", "")
    return (cid, secret) if cid and secret else None


def configured() -> bool:
    """Report whether Evolved can start the official Toolhub OAuth flow."""
    return oauth_client() is not None


def authorize_url(*, state: str, redirect_uri: str) -> str:
    """Build the official Toolhub authorization URL."""
    client = oauth_client()
    if client is None:
        msg = "Toolhub OAuth is not configured"
        raise ToolhubAuthError(msg)
    params = urlencode(
        {
            "response_type": "code",
            "client_id": client[0],
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"{base_url()}/o/authorize/?{params}"


def exchange_code(*, code: str, redirect_uri: str) -> dict[str, object]:
    """Exchange an authorization code for official Toolhub tokens."""
    client = oauth_client()
    if client is None:
        msg = "Toolhub OAuth is not configured"
        raise ToolhubAuthError(msg)
    resp = requests.post(
        f"{base_url()}/o/token/",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client[0],
            "client_secret": client[1],
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_grant(refresh_token: str) -> dict[str, object]:
    """Refresh an official Toolhub OAuth token."""
    client = oauth_client()
    if client is None:
        msg = "Toolhub OAuth is not configured"
        raise ToolhubAuthError(msg)
    resp = requests.post(
        f"{base_url()}/o/token/",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client[0],
            "client_secret": client[1],
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def current_user(access_token: str) -> dict[str, object]:
    """Fetch the official Toolhub identity represented by an access token."""
    data, _status = request_with_token("GET", "/api/user/", access_token=access_token)
    if not isinstance(data, dict) or data.get("is_authenticated") is False:
        msg = "Official Toolhub did not return an authenticated user"
        raise ToolhubAuthError(msg)
    return data


def _expires_at(token_payload: dict[str, object]) -> datetime | None:
    raw = token_payload.get("expires_in")
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return None
    return datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(seconds=seconds)


def save_grant(user_id: int, token_payload: dict[str, object]) -> None:
    """Store or replace the official Toolhub OAuth grant for a local user."""
    access_token = token_crypto.encrypt(str(token_payload["access_token"]))
    refresh = token_payload.get("refresh_token")
    with db.session_scope() as s:
        row = s.get(ToolhubToken, user_id)
        if row is None:
            row = ToolhubToken(user_id=user_id, access_token=access_token)
            s.add(row)
        row.access_token = access_token
        if refresh:
            row.refresh_token = token_crypto.encrypt(str(refresh))
        row.token_type = str(token_payload.get("token_type") or "Bearer")
        row.scope = str(token_payload.get("scope") or SCOPES)
        row.expires_at = _expires_at(token_payload)
        row.updated_at = utcnow()


def revoke_local_grant(user_id: int) -> None:
    """Forget a user's local copy of the official Toolhub grant."""
    with db.session_scope() as s:
        row = s.get(ToolhubToken, user_id)
        if row is not None:
            s.delete(row)


def _needs_refresh(row: ToolhubToken) -> bool:
    if row.expires_at is None:
        return False
    return row.expires_at <= utcnow() + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)


def _open_grant(row: ToolhubToken) -> tuple[str, str | None]:
    """Decrypt one stored grant, re-sealing it if it predates encryption.

    Re-sealing here drains the plaintext tolerance in backend.token_crypto, so
    the compatibility path removes itself as users make writes.
    """
    access = token_crypto.decrypt(row.access_token)
    refresh = token_crypto.decrypt(row.refresh_token) if row.refresh_token else None
    if not token_crypto.is_encrypted(row.access_token):
        row.access_token = token_crypto.encrypt(access)
        if refresh:
            row.refresh_token = token_crypto.encrypt(refresh)
    return access, refresh


def _grant_for_user(user_id: int) -> ToolhubToken:
    try:
        return _load_grant(user_id)
    except token_crypto.GrantDecryptionError as exc:
        # The key rotated, or this row was written under a different one. There
        # is nothing to recover, so fail closed: forget the unusable grant and
        # ask for re-authorization rather than 500 on every future write. The
        # delete needs its own transaction because session_scope() rolls back
        # the one that raised.
        revoke_local_grant(user_id)
        msg = "Official Toolhub authorization must be renewed"
        raise ToolhubAuthError(msg) from exc


def _load_grant(user_id: int) -> ToolhubToken:
    with db.session_scope() as s:
        row = s.execute(select(ToolhubToken).where(ToolhubToken.user_id == user_id)).scalar_one_or_none()
        if row is None:
            msg = "Official Toolhub authorization is required"
            raise ToolhubAuthError(msg)
        access, refresh = _open_grant(row)
        if _needs_refresh(row):
            if not refresh:
                msg = "Official Toolhub authorization expired"
                raise ToolhubAuthError(msg)
            refreshed = refresh_grant(refresh)
            access = str(refreshed["access_token"])
            row.access_token = token_crypto.encrypt(access)
            if refreshed.get("refresh_token"):
                refresh = str(refreshed["refresh_token"])
                row.refresh_token = token_crypto.encrypt(refresh)
            row.token_type = str(refreshed.get("token_type") or row.token_type or "Bearer")
            row.scope = str(refreshed.get("scope") or row.scope or SCOPES)
            row.expires_at = _expires_at(refreshed)
            row.updated_at = utcnow()
            s.flush()
        # Detached copy carries plaintext: it is request-scoped and never persisted.
        return ToolhubToken(
            user_id=row.user_id,
            access_token=access,
            refresh_token=refresh,
            token_type=row.token_type,
            scope=row.scope,
            expires_at=row.expires_at,
            updated_at=row.updated_at,
        )


def _json_or_text(resp: requests.Response) -> object:
    try:
        return resp.json()
    except ValueError:
        return {"message": resp.text}


def _public_api_url(path: str, params: dict[str, object] | None = None) -> str:
    """Build a fixed anonymous Toolhub API URL for cacheable GET reads."""
    normalized = "/" + path.lstrip("/")
    if normalized != "/api/" and not normalized.startswith("/api/"):
        msg = "anonymous reads are limited to Toolhub /api/"
        raise ValueError(msg)
    # The prefix check alone is not enough: requests normalizes dot segments, so
    # "/api/../o/token/" would satisfy it and then leave the /api/ tree.
    if any(part == ".." for part in normalized.split("/")):
        msg = "anonymous reads may not use parent-directory segments"
        raise ValueError(msg)
    pairs = [(key, value) for key, value in (params or {}).items() if value is not None]
    query = urlencode(pairs, doseq=True)
    return f"{base_url()}{normalized}{('?' + query) if query else ''}"


def _cached_json_payload(hit: api_cache.CachedResponse) -> object:
    """Decode one JSON response stored in the anonymous Toolhub API cache."""
    return loads(hit.body.decode("utf-8"))


def public_api_get(path: str, *, params: dict[str, object] | None = None) -> object:
    """GET anonymous official Toolhub API JSON through the shared persistent cache."""
    url = _public_api_url(path, params)
    cached = api_cache.get(url)
    if cached is not None:
        return _cached_json_payload(cached)

    resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
    payload = _json_or_text(resp)
    if not resp.ok:
        raise ToolhubAPIError(resp.status_code, payload)

    if _CACHEABLE_MIN_STATUS <= resp.status_code < _CACHEABLE_MAX_STATUS:
        body = resp.content or dumps(payload).encode("utf-8")
        api_cache.put_success(
            url,
            api_cache.CacheableResponse(
                status=resp.status_code,
                content_type=resp.headers.get("content-type", "application/json"),
                body=body,
                etag=resp.headers.get("etag"),
                last_modified=resp.headers.get("last-modified"),
            ),
        )
    return payload


def request_with_token(method: str, path: str, *, access_token: str, json: object | None = None) -> tuple[object, int]:
    """Call the official Toolhub API with a supplied OAuth access token."""
    resp = requests.request(
        method,
        f"{base_url()}{path}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        json=json,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == HTTP_NO_CONTENT:
        return {"ok": True}, HTTP_NO_CONTENT
    payload = _json_or_text(resp)
    if not resp.ok:
        raise ToolhubAPIError(resp.status_code, payload)
    return payload, resp.status_code


def api_request(user_id: int, method: str, path: str, *, json: object | None = None) -> tuple[object, int]:
    """Call the official Toolhub API using a stored user grant."""
    grant = _grant_for_user(user_id)
    return request_with_token(method, path, access_token=grant.access_token, json=json)
