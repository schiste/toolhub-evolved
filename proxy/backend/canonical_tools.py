# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured local cache of canonical official Toolhub tool records."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend import db
from backend.api_cache import DETAIL_FRESH_SECONDS, SEARCH_FRESH_SECONDS, STALE_IF_ERROR_SECONDS
from backend.models import CanonicalToolCache, utcnow
from backend.sync import SOURCE_OFFICIAL, SYNC_OFFICIAL

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MAX_INGEST_TOOLS = 100
MAX_QUERY_NAMES = 50
MAX_SEARCH_RESULTS = 50
MAX_SOURCE_URL = 2000
TOOL_DETAIL_PARTS = 3
MAX_RECORD_RESULTS = 5000
TOOLSADMIN_HOST = "toolsadmin.wikimedia.org"


def _clean_name(value: Any) -> str:  # noqa: ANN401 - untrusted official API JSON
    return str(value or "").strip()[:255]


def _path(url: str) -> str:
    return urlparse(url).path.rstrip("/") + "/"


def _path_parts(url: str) -> list[str]:
    return [unquote(part) for part in _path(url).strip("/").split("/") if part]


def toolforge_project_names(tool_name: str, record: dict[str, Any] | None) -> list[str]:
    """Return Toolforge projects proven by one canonical Toolhub record.

    Toolhub names are user-supplied catalog identifiers, so the conventional
    ``toolforge-`` prefix is useful but not universal. Toolforge deployment
    hosts and Toolsadmin project URLs provide equally strong project aliases.
    """
    candidates: list[str] = []
    clean_tool_name = _clean_name(tool_name)
    if clean_tool_name.casefold().startswith("toolforge-"):
        candidates.append(clean_tool_name[len("toolforge-") :])
    source = record if isinstance(record, dict) else {}
    for key in ("url", "api_url"):
        raw_url = str(source.get(key) or "").strip()
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").casefold()
        if host.endswith(".toolforge.org"):
            candidates.append(host.removesuffix(".toolforge.org"))
        if host == TOOLSADMIN_HOST:
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            for index in range(len(parts) - 2):
                if parts[index : index + 2] == ["tools", "id"]:
                    candidates.append(parts[index + 2])
                    break
    names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = _clean_name(candidate)
        normalized = clean.casefold()
        if clean and normalized not in seen:
            seen.add(normalized)
            names.append(clean)
    return names


def names_by_toolforge_project(s: Session) -> dict[str, tuple[str, ...]]:
    """Index canonical Toolhub names by strongly inferred Toolforge project."""
    index: dict[str, set[str]] = {}
    rows = s.execute(select(CanonicalToolCache.tool_name, CanonicalToolCache.record)).all()
    for tool_name, record in rows:
        for project in toolforge_project_names(tool_name, record):
            index.setdefault(project.casefold(), set()).add(tool_name)
    return {
        project: tuple(sorted(tool_names, key=lambda value: (value.casefold(), value)))
        for project, tool_names in index.items()
    }


def _is_tool_record(value: Any) -> bool:  # noqa: ANN401 - untrusted official API JSON
    if not isinstance(value, dict):
        return False
    if not _clean_name(value.get("name")):
        return False
    return any(key in value for key in ("title", "description", "url", "tool_type", "author", "modified_date"))


def _iter_tool_records(value: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - untrusted official API JSON
    out: list[dict[str, Any]] = []
    stack = [value]
    while stack and len(out) < MAX_INGEST_TOOLS:
        current = stack.pop()
        if _is_tool_record(current):
            out.append(current)
            continue
        if isinstance(current, dict):
            for key in ("results", "tools", "featured", "recent", "most_listed"):
                nested = current.get(key)
                if isinstance(nested, list | dict):
                    stack.append(nested)
        elif isinstance(current, list):
            stack.extend(reversed(current))
    return out


def ingest_payload(url: str, body: bytes) -> int:
    """Extract official tool records from one cached Toolhub API payload."""
    path = _path(url)
    if not (path.startswith(("/api/tools/", "/api/lists/")) or path in {"/api/search/tools/", "/api/ui/home/"}):
        return 0
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0
    records = _iter_tool_records(payload)
    if not records:
        return 0
    return upsert_records(records, source_url=url, detail=is_tool_detail_url(url))


def is_tool_detail_url(url: str) -> bool:
    parts = _path_parts(url)
    return len(parts) == TOOL_DETAIL_PARTS and parts[0] == "api" and parts[1] == "tools" and bool(parts[2])


def _has_value(value: Any) -> bool:  # noqa: ANN401 - official API JSON
    return value not in (None, "", [], {})


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a query for "100%" is not a match-anything pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _merge_listing_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Apply listing fields without erasing richer detail-only metadata."""
    merged = dict(existing)
    for key, value in incoming.items():
        if _has_value(value) or key not in merged:
            merged[key] = value
    return merged


def upsert_records(
    records: list[dict[str, Any]],
    *,
    source_url: str,
    detail: bool = False,
    generation: int | None = None,
    enqueue_reconciliation: bool = True,
) -> int:
    """Persist canonical official tool records into the structured cache."""
    now = utcnow()
    fresh = DETAIL_FRESH_SECONDS if detail else SEARCH_FRESH_SECONDS
    expires_at = now + timedelta(seconds=fresh)
    stale_until = now + timedelta(seconds=fresh + STALE_IF_ERROR_SECONDS)
    seen: set[str] = set()
    clean_records: list[tuple[str, dict[str, Any]]] = []
    for record in records:
        name = _clean_name(record.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        clean_records.append((name, record))
    if not clean_records:
        return 0
    try:
        with db.session_scope() as s:
            for name, record in clean_records:
                row = s.get(CanonicalToolCache, name)
                existing_is_detail = bool(row and is_tool_detail_url(row.source_url))
                if row is None:
                    row = CanonicalToolCache(tool_name=name)
                    s.add(row)
                # search_text follows automatically: the model derives it from
                # every `record` assignment (see CanonicalToolCache).
                row.record = record if detail else _merge_listing_record(row.record or {}, record)
                if detail or not existing_is_detail:
                    row.source_url = source_url[:MAX_SOURCE_URL]
                    row.expires_at = expires_at
                    row.stale_until = stale_until
                row.source = SOURCE_OFFICIAL
                row.sync_status = SYNC_OFFICIAL
                row.fetched_at = now
                row.last_error = None
                if generation is not None:
                    row.generation = generation
    except SQLAlchemyError:
        return 0
    # Queue only after the canonical transaction succeeds. Processing is
    # asynchronous so anonymous API requests do not wait on derived indexes.
    if enqueue_reconciliation:
        from backend.people_reconcile import enqueue_tool_names  # noqa: PLC0415 - avoid backend startup cycles.

        enqueue_tool_names([name for name, _record in clean_records], reason="canonical_fetch")
    return len(clean_records)


def prune_completed_generation(s: Session, generation: int, expected_count: int) -> list[str]:
    """Delete names absent from one fully validated official catalog snapshot.

    A partial or internally inconsistent generation raises without deleting
    anything. This is the same safety boundary used by the account projection:
    upstream absence is authoritative only after every page agrees on the
    snapshot size.
    """
    observed = int(
        s.scalar(
            select(func.count()).select_from(CanonicalToolCache).where(CanonicalToolCache.generation == generation)
        )
        or 0
    )
    if observed != expected_count:
        msg = f"catalog generation {generation} saw {observed} distinct rows, expected {expected_count}"
        raise ValueError(msg)
    retired = list(
        s.execute(
            select(CanonicalToolCache.tool_name)
            .where(CanonicalToolCache.generation != generation)
            .order_by(CanonicalToolCache.tool_name)
        ).scalars()
    )
    if retired:
        s.execute(delete(CanonicalToolCache).where(CanonicalToolCache.generation != generation))
    return retired


def backfill_search_text(*, batch_size: int = 500) -> int:
    """Populate search_text for rows cached before the column existed.

    Without it every pre-existing row is invisible to search() until some later
    sync happens to rewrite it, which for the canonical catalog could be hours.

    Run from proxy/migrate.py, not from schema setup: this reads and rewrites
    every row, and the catalog is thousands of rows with a full JSON record
    each. Batched into short transactions so it never holds locks on a table
    that live reads need, and safe to run repeatedly.
    """
    filled = 0
    while True:
        try:
            with db.session_scope() as s:
                rows = list(
                    s.execute(
                        select(CanonicalToolCache)
                        .where((CanonicalToolCache.search_text == "") | CanonicalToolCache.search_text.is_(None))
                        .limit(batch_size)
                    ).scalars()
                )
                if not rows:
                    return filled
                for row in rows:
                    row.record = row.record or {}  # reassignment re-derives search_text
                    filled += 1
        except SQLAlchemyError:
            return filled


def _payload(row: CanonicalToolCache) -> dict[str, Any]:
    return {
        "toolName": row.tool_name,
        "record": row.record,
        "sourceUrl": row.source_url,
        "source": row.source or SOURCE_OFFICIAL,
        "syncStatus": row.sync_status or SYNC_OFFICIAL,
        "fetchedAt": row.fetched_at.isoformat(timespec="seconds") + "Z" if row.fetched_at else "",
        "expiresAt": row.expires_at.isoformat(timespec="seconds") + "Z" if row.expires_at else "",
        "staleUntil": row.stale_until.isoformat(timespec="seconds") + "Z" if row.stale_until else "",
        "stale": bool(row.expires_at and row.expires_at <= utcnow()),
        "lastError": row.last_error or "",
    }


def tools_by_name(names: list[str]) -> dict[str, dict[str, Any]]:
    """Return cached canonical tool records by exact Toolhub name."""
    clean_names = []
    seen: set[str] = set()
    for name in names:
        clean = _clean_name(name)
        if clean and clean not in seen:
            seen.add(clean)
            clean_names.append(clean)
    clean_names = clean_names[:MAX_QUERY_NAMES]
    if not clean_names:
        return {}
    with db.session_scope() as s:
        rows = list(
            s.execute(select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(clean_names))).scalars()
        )
    return {row.tool_name: _payload(row) for row in rows}


def _fts_match_expression(term: str) -> str:
    """Convert raw user input into safe FTS5 phrase tokens.

    FTS5 MATCH has operator syntax ("-", ":", quotes) that raises on arbitrary
    input; quoting every whitespace token as a phrase makes any input legal
    and means multi-word queries require all words (implicit AND). The
    trailing token gets a prefix star because interactive callers send
    partial words ("citat") that must still match.
    """
    tokens = [t.replace('"', '""') for t in term.split() if t]
    if not tokens:
        return ""
    quoted = [f'"{t}"' for t in tokens]
    quoted[-1] = f"{quoted[-1]}*"
    return " ".join(quoted)


def _boolean_match_expression(term: str) -> str:
    """MariaDB BOOLEAN MODE expression: every token required, prefix-matched.

    Boolean mode (unlike natural-language mode) supports the trailing "*",
    which is what keeps partial-word queries working; operator characters in
    user input are stripped rather than escaped because none of them occur in
    tool vocabulary.
    """
    tokens = ["".join(ch for ch in t if ch not in '+-<>()~*"@') for t in term.split()]
    return " ".join(f"+{t}*" for t in tokens if t)


def _search_ranked(s: Session, term: str, capped: int) -> list[dict[str, Any]] | None:
    """Relevance-ordered payloads via the dialect's ranked index, or None.

    Takes the caller's session: one search must not cost three transactions.
    """
    match = _fts_match_expression(term)
    if not match:
        return None
    try:
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            names = [
                row[0]
                for row in s.execute(
                    text(
                        "SELECT tool_name FROM canonical_tool_search "
                        "WHERE canonical_tool_search MATCH :match "
                        "ORDER BY rank LIMIT :limit"
                    ),
                    {"match": match, "limit": capped},
                )
            ]
        elif dialect in ("mysql", "mariadb"):
            boolean = _boolean_match_expression(term)
            if not boolean:
                return None
            names = [
                row[0]
                for row in s.execute(
                    text(
                        "SELECT tool_name FROM canonical_tool_cache "
                        "WHERE MATCH(search_text) AGAINST(:q IN BOOLEAN MODE) "
                        "ORDER BY MATCH(search_text) AGAINST(:q IN BOOLEAN MODE) DESC "
                        "LIMIT :limit"
                    ),
                    {"q": boolean, "limit": capped},
                )
            ]
        else:
            return None
        rows = {
            row.tool_name: row
            for row in s.execute(select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(names))).scalars()
        }
        return [_payload(rows[name]) for name in names if name in rows]
    except SQLAlchemyError:
        # Missing index (fresh DB before migrate has run): degrade to LIKE
        # rather than failing reads.
        return None


def search(query: str = "", *, limit: int = MAX_SEARCH_RESULTS) -> list[dict[str, Any]]:
    """Search cached canonical records, best matches first.

    Relevance-ranked via the dialect's full-text index when available,
    topped up by the deterministic substring path so partial-word recall
    ("citat", "sf") never regresses; recency-ordered listing when the query
    is empty. Filtering and limiting happen in SQL.
    """
    term = str(query or "").strip().casefold()
    capped = max(1, min(MAX_SEARCH_RESULTS, int(limit or MAX_SEARCH_RESULTS)))
    statement = select(CanonicalToolCache).order_by(CanonicalToolCache.fetched_at.desc(), CanonicalToolCache.tool_name)
    with db.session_scope() as s:
        if not term:
            return [_payload(row) for row in s.execute(statement.limit(capped)).scalars()]
        ranked = _search_ranked(s, term, capped) or []
        if len(ranked) >= capped:
            return ranked
        # Top up from the substring path: token/prefix matching cannot see
        # mid-word fragments ("dits"), and MariaDB drops sub-3-char tokens
        # and stopwords entirely. Ranked hits keep their order and lead.
        # Over-fetch by the ranked count so dedup can't shrink a full page.
        found = {payload["toolName"] for payload in ranked}
        like_statement = statement.where(
            CanonicalToolCache.search_text.like(f"%{_escape_like(term)}%", escape="\\")
        ).limit(capped + len(found))
        extras = [_payload(row) for row in s.execute(like_statement).scalars() if row.tool_name not in found]
    return (ranked + extras)[:capped]


def records(*, limit: int = MAX_RECORD_RESULTS) -> list[dict[str, Any]]:
    """Return recent canonical records for deterministic derived indexes."""
    capped = max(1, min(MAX_RECORD_RESULTS, int(limit or MAX_RECORD_RESULTS)))
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(CanonicalToolCache)
                .order_by(CanonicalToolCache.fetched_at.desc(), CanonicalToolCache.tool_name)
                .limit(capped)
            ).scalars()
        )
    return [_payload(row) for row in rows]
