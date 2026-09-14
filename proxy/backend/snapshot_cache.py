# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared persistence and lock semantics for expensive JSON snapshots."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from backend import db
from backend.models import ApiCacheMeta

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SnapshotBuilder = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class SnapshotPolicy:
    """Cache identity and freshness rules for one expensive snapshot."""

    key: str
    lock_name: str
    stale_limit: timedelta


def load(session: Session, key: str) -> tuple[ApiCacheMeta | None, dict[str, Any] | None]:
    """Load a cache row and decode a usable object payload."""
    cached = session.get(ApiCacheMeta, key)
    if cached is None:
        return None, None
    try:
        decoded = json.loads(cached.value)
    except json.JSONDecodeError:
        return cached, None
    return cached, decoded if isinstance(decoded, dict) else None


def store(session: Session, key: str, payload: dict[str, Any], now: datetime) -> None:
    """Persist a deterministic snapshot payload in its cache row."""
    cached = session.get(ApiCacheMeta, key)
    if cached is None:
        cached = ApiCacheMeta(key=key, value="")
        session.add(cached)
    cached.value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    cached.updated_at = now


def get_or_rebuild(
    *,
    policy: SnapshotPolicy,
    force: bool,
    now: datetime,
    builder: SnapshotBuilder,
    database: Any = db,  # noqa: ANN401 - small DB facade used by tests and callers
) -> dict[str, Any]:
    """Serve a usable snapshot or rebuild it under one advisory lock.

    The fast path intentionally uses one session and no lock. Once a payload is
    missing or too old, the lock serializes rebuilds and the holder re-reads the
    cache before paying for another full-catalog pass. Callers can inject their
    DB facade so existing tests can observe lock acquisition without coupling
    this infrastructure module to one module's global binding.
    """
    with database.session_scope() as session:
        cached, cached_payload = load(session, policy.key)
        if cached_payload is not None and not force and cached.updated_at >= now - policy.stale_limit:
            return cached_payload

    with (
        database.advisory_lock(policy.lock_name, timeout_seconds=2) as acquired,
        database.session_scope() as session,
    ):
        cached, cached_payload = load(session, policy.key)
        if cached_payload is not None and not force and (cached.updated_at >= now - policy.stale_limit or not acquired):
            return cached_payload
        payload = builder(session, now=now.astimezone(UTC))
        if acquired:
            store(session, policy.key, payload, now)
        return payload


def refresh(
    *,
    policy: SnapshotPolicy,
    now: datetime,
    builder: SnapshotBuilder,
    database: Any = db,  # noqa: ANN401 - small DB facade used by tests and callers
) -> tuple[bool, dict[str, Any] | None]:
    """Build and store a snapshot only when this caller owns the lock."""
    with (
        database.advisory_lock(policy.lock_name, timeout_seconds=2) as acquired,
        database.session_scope() as session,
    ):
        if not acquired:
            return False, None
        payload = builder(session, now=now.astimezone(UTC))
        store(session, policy.key, payload, now)
        return True, payload
