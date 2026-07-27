# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent cache for anonymous official Toolhub API reads."""

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from backend import db
from backend.models import ApiCache, utcnow

FRESH_SECONDS = 30
STALE_SECONDS = 5 * 60


@dataclass(frozen=True)
class CachedResponse:
    """A detached cached HTTP response body."""

    status: int
    content_type: str
    body: bytes
    stale: bool
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class CacheableResponse:
    """A successful upstream response ready to persist."""

    status: int
    content_type: str
    body: bytes
    etag: str | None = None
    last_modified: str | None = None


def _key(url: str) -> str:
    """Return a compact, index-safe cache key for an upstream URL."""
    return sha256(url.encode("utf-8")).hexdigest()


def get(url: str, *, allow_stale: bool = False) -> CachedResponse | None:
    """Return a fresh cache hit, or a stale hit when explicitly allowed."""
    now = utcnow()
    try:
        with db.session_scope() as s:
            row = s.get(ApiCache, _key(url))
            if row is None:
                return None
            if row.expires_at > now:
                stale = False
            elif allow_stale and row.stale_until > now:
                stale = True
            else:
                return None
            return CachedResponse(
                status=row.status,
                content_type=row.content_type,
                body=bytes(row.body),
                stale=stale,
                etag=row.etag,
                last_modified=row.last_modified,
            )
    except SQLAlchemyError:
        return None


def put_success(
    url: str,
    upstream: CacheableResponse,
    *,
    fresh_seconds: int = FRESH_SECONDS,
    stale_seconds: int = STALE_SECONDS,
) -> None:
    """Store a successful anonymous Toolhub API response."""
    now = utcnow()
    row = ApiCache(
        url_hash=_key(url),
        url=url,
        status=upstream.status,
        content_type=upstream.content_type,
        body=upstream.body,
        fetched_at=now,
        expires_at=now + timedelta(seconds=fresh_seconds),
        stale_until=now + timedelta(seconds=stale_seconds),
        etag=upstream.etag,
        last_modified=upstream.last_modified,
        last_error=None,
    )
    try:
        with db.session_scope() as s:
            s.merge(row)
    except SQLAlchemyError:
        # Cache persistence must never break live reads.
        return


def refresh(url: str, *, fresh_seconds: int = FRESH_SECONDS, stale_seconds: int = STALE_SECONDS) -> None:
    """Refresh cache timestamps after upstream confirms the cached body is current."""
    now = utcnow()
    try:
        with db.session_scope() as s:
            row = s.get(ApiCache, _key(url))
            if row is None:
                return
            row.fetched_at = now
            row.expires_at = now + timedelta(seconds=fresh_seconds)
            row.stale_until = now + timedelta(seconds=stale_seconds)
            row.last_error = None
    except SQLAlchemyError:
        return


def mark_failure(url: str, error: str) -> None:
    """Record the latest revalidation failure without caching an error body."""
    try:
        with db.session_scope() as s:
            row = s.get(ApiCache, _key(url))
            if row is not None:
                row.last_error = error[:2000]
    except SQLAlchemyError:
        return


def clear() -> None:
    """Clear the API cache, used by tests and operator cleanup scripts."""
    with db.session_scope() as s:
        s.execute(delete(ApiCache))
