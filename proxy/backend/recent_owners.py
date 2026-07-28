# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared owner-by-tool cache for the Recent changes page."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy.exc import SQLAlchemyError

from backend import db, toolhub
from backend.models import ToolOwnerCache, utcnow

OWNER_FRESH_SECONDS = 24 * 60 * 60
OWNER_STALE_SECONDS = 7 * 24 * 60 * 60
OWNER_NEGATIVE_FRESH_SECONDS = 60 * 60
OWNER_MAX_NAMES = 50
OWNER_ERROR_LIMIT = 2000
# Live upstream fetches one resolve_owners() call may trigger. Cache hits are
# free; only cold names spend budget. The Recent page asks about tools that the
# prewarm job already warmed, so it effectively never reaches this — but without
# it a single anonymous request fans out into OWNER_MAX_NAMES requests at
# toolhub.wikimedia.org. Callers pass None (the scheduled job) to opt out.
OWNER_FETCH_BUDGET = 10
SOURCE_DEFERRED = "deferred"


@dataclass(frozen=True)
class OwnerResult:
    """One resolved owner label and its cache metadata."""

    tool_name: str
    owner: str
    source: str
    cached: bool
    stale: bool = False


def clean_tool_names(values: list[Any], *, limit: int = OWNER_MAX_NAMES) -> list[str]:
    """Return unique non-empty Toolhub tool names, preserving first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value or "").strip()
        key = name.casefold()
        if name and key not in seen:
            out.append(name[:255])
            seen.add(key)
        if len(out) >= limit:
            break
    return out


def owner_from_tool_record(raw: Any) -> str:  # noqa: ANN401 - untrusted Toolhub JSON
    """Extract the display owner label the Recent table should show."""
    if not isinstance(raw, dict):
        return ""
    author = raw.get("author")
    authors = author if isinstance(author, list) else [author]
    for item in authors:
        if isinstance(item, dict):
            for key in ("name", "developer_username", "wiki_username"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
        elif isinstance(item, str | int | float):
            value = str(item).strip()
            if value:
                return value
    created_by = raw.get("created_by")
    if isinstance(created_by, dict):
        return str(created_by.get("username") or "").strip()
    return ""


def _row_payload(row: ToolOwnerCache, *, stale: bool = False) -> OwnerResult:
    return OwnerResult(row.tool_name, row.owner or "", row.source or "toolhub_detail", cached=True, stale=stale)


def _cached_owner(tool_name: str) -> OwnerResult | None:
    now = utcnow()
    try:
        with db.session_scope() as s:
            row = s.get(ToolOwnerCache, tool_name)
            if row is None:
                return None
            if row.expires_at > now:
                return _row_payload(row)
            if row.stale_until > now:
                return _row_payload(row, stale=True)
    except SQLAlchemyError:
        return None
    return None


def _store_owner(tool_name: str, owner: str, *, source: str = "toolhub_detail", error: str | None = None) -> None:
    now = utcnow()
    fresh_seconds = OWNER_FRESH_SECONDS if owner else OWNER_NEGATIVE_FRESH_SECONDS
    row = ToolOwnerCache(
        tool_name=tool_name,
        owner=owner[:255],
        source=source,
        fetched_at=now,
        expires_at=now + timedelta(seconds=fresh_seconds),
        stale_until=now + timedelta(seconds=fresh_seconds + OWNER_STALE_SECONDS),
        last_error=error[:OWNER_ERROR_LIMIT] if error else None,
    )
    try:
        with db.session_scope() as s:
            s.merge(row)
    except SQLAlchemyError:
        return


def _mark_failure(tool_name: str, error: str) -> None:
    try:
        with db.session_scope() as s:
            row = s.get(ToolOwnerCache, tool_name)
            if row is not None:
                row.last_error = error[:OWNER_ERROR_LIMIT]
    except SQLAlchemyError:
        return


def _fetch_owner(tool_name: str) -> OwnerResult:
    try:
        tool = toolhub.public_api_get(f"/api/tools/{quote(tool_name, safe='')}/")
        owner = owner_from_tool_record(tool)
        _store_owner(tool_name, owner)
        return OwnerResult(tool_name, owner, "toolhub_detail", cached=False)
    except Exception as exc:  # noqa: BLE001 - owner enrichment must never break Recent.
        cached = _cached_owner(tool_name)
        if cached is not None:
            _mark_failure(tool_name, str(exc))
            return cached
        _store_owner(tool_name, "", error=str(exc))
        return OwnerResult(tool_name, "", "toolhub_error", cached=False)


def resolve_owners(tool_names: list[Any], *, fetch_budget: int | None = None) -> dict:
    """Resolve owner labels for a bounded set of recent-change tool names.

    `fetch_budget` caps how many names may be resolved by going upstream in one
    call; None means unlimited. Names beyond the budget come back with an empty
    owner and source SOURCE_DEFERRED, and are deliberately *not* written to the
    owner cache — a deferred name is unknown, not known-empty, so callers must
    be able to ask again.
    """
    names = clean_tool_names(tool_names)
    owners: dict[str, str] = {}
    meta: dict[str, dict[str, Any]] = {}
    remaining = fetch_budget
    for name in names:
        cached = _cached_owner(name)
        if cached is not None and not cached.stale:
            result = cached
        elif remaining is None or remaining > 0:
            result = _fetch_owner(name)
            if remaining is not None:
                remaining -= 1
        else:
            result = OwnerResult(name, "", SOURCE_DEFERRED, cached=False)
        owners[name] = result.owner
        meta[name] = {"source": result.source, "cached": result.cached, "stale": result.stale}
    return {"count": len(names), "owners": owners, "meta": meta}
