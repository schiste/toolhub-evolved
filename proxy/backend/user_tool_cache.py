# SPDX-License-Identifier: GPL-3.0-or-later
"""Private persistent cache for the expensive per-user Toolhub resolver."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from sqlalchemy import select

from backend import db
from backend.models import UserToolResolverCache, utcnow
from backend.sync import clean_error

FRESH_SECONDS = 15 * 60
STALE_SECONDS = 7 * 24 * 60 * 60
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="user-tool-resolver")
_REFRESH_LOCK = Lock()
_REFRESHING: set[int] = set()


@dataclass(frozen=True)
class CacheRead:
    payload: dict[str, Any]
    metadata: dict[str, str]


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") + "Z" if value is not None else ""


def _metadata(row: UserToolResolverCache, status: str) -> dict[str, str]:
    return {
        "status": status,
        "computedAt": _iso(row.computed_at),
        "expiresAt": _iso(row.expires_at),
        "staleUntil": _iso(row.stale_until),
    }


def read(user_id: int) -> CacheRead | None:
    """Return a fresh or stale private payload, never an expired one."""
    now = utcnow()
    try:
        with db.session_scope() as s:
            row = s.get(UserToolResolverCache, user_id)
            if row is None or now >= row.stale_until:
                return None
            status = "fresh" if now < row.expires_at else "stale"
            return CacheRead(dict(row.payload or {}), _metadata(row, status))
    except Exception:  # noqa: BLE001 - cache failures must not break the resolver.
        return None


def store(user_id: int, payload: dict[str, Any]) -> None:
    """Persist one successful resolver result with fresh/stale windows."""
    now = utcnow()
    with db.session_scope() as s:
        row = s.get(UserToolResolverCache, user_id) or UserToolResolverCache(user_id=user_id)
        row.payload = payload
        row.computed_at = now
        row.expires_at = now + timedelta(seconds=FRESH_SECONDS)
        row.stale_until = now + timedelta(seconds=FRESH_SECONDS + STALE_SECONDS)
        row.last_error = None
        s.add(row)


def record_error(user_id: int, error: Exception) -> None:
    """Keep stale data usable while recording a background refresh failure."""
    try:
        with db.session_scope() as s:
            row = s.get(UserToolResolverCache, user_id)
            if row is not None:
                row.last_error = clean_error(str(error))
    except Exception:  # noqa: BLE001 - error reporting cannot become a second failure.
        return


def _worker(user_id: int, refresh: Callable[[int], dict[str, Any] | None]) -> None:
    try:
        payload = refresh(user_id)
        if payload is not None:
            store(user_id, payload)
    except Exception as exc:  # noqa: BLE001 - background refresh must not affect readers.
        record_error(user_id, exc)
    finally:
        with _REFRESH_LOCK:
            _REFRESHING.discard(user_id)


def queue_refresh(user_id: int, refresh: Callable[[int], dict[str, Any] | None]) -> None:
    """Queue at most one refresh per user."""
    with _REFRESH_LOCK:
        if user_id in _REFRESHING:
            return
        _REFRESHING.add(user_id)
    _EXECUTOR.submit(_worker, user_id, refresh)
