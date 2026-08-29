# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured local cache of the tool records the catalog is built from.

Mostly the official Toolhub catalog, synced wholesale as numbered
generations. Not only that: records synthesized from public wiki data live
here too, because a card, a facet, a search hit and an author edge all hang
off a row existing in this table. What separates the two is `source`, and
the generation prune is scoped by it -- see `_prune_superseded`.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from backend import catalog_facets, db
from backend.api_cache import DETAIL_FRESH_SECONDS, SEARCH_FRESH_SECONDS, STALE_IF_ERROR_SECONDS
from backend.models import ApiCacheMeta, CanonicalToolCache, CatalogSnapshotStage, catalog_card_record, utcnow
from backend.sync import SOURCE_OFFICIAL, SYNC_OFFICIAL

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.elements import ColumnElement

MAX_INGEST_TOOLS = 100
MAX_QUERY_NAMES = 50
MAX_SEARCH_RESULTS = 50
# Terms honored from one free-text query. A longer query is truncated rather
# than refused: an LLM caller that pastes a whole sentence should get the best
# match for its leading content words, not an error. Truncation drops
# conjuncts, so it can only widen the result set -- it can never hide a tool a
# shorter query would have found.
MAX_SEARCH_TERMS = 8
MAX_SOURCE_URL = 2000
TOOL_DETAIL_PARTS = 3
MAX_RECORD_RESULTS = 5000
TOOLSADMIN_HOST = "toolsadmin.wikimedia.org"
# Hosts that put the project in the first path segment rather than the subdomain.
LEGACY_TOOLFORGE_PATH_HOSTS = ("tools.wmflabs.org", "tools-static.wmflabs.org")
# Suffixes whose subdomain names a project. Checked after the path hosts above,
# so `tools.wmflabs.org` is never misread as a project called "tools".
RUNTIME_HOST_SUFFIXES = (".toolforge.org", ".wmflabs.org", ".wmcloud.org")
READ_PROJECTION_META_KEY = "catalog:read-projection:v1"


def _clean_name(value: Any) -> str:  # noqa: ANN401 - untrusted official API JSON
    return str(value or "").strip()[:255]


def compact_record(record: dict[str, Any] | None) -> dict[str, Any]:
    """Return the stable card/list representation of one canonical record."""
    return catalog_card_record(record)


def _path(url: str) -> str:
    return urlparse(url).path.rstrip("/") + "/"


def _path_parts(url: str) -> list[str]:
    return [unquote(part) for part in _path(url).strip("/").split("/") if part]


def _dedupe_project_names(candidates: list[str]) -> list[str]:
    """Return cleaned project names in evidence-precedence order."""
    names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = _clean_name(candidate)
        normalized = clean.casefold()
        if clean and normalized not in seen:
            seen.add(normalized)
            names.append(clean)
    return names


def _collapse_hyphens(value: str) -> str:
    """Collapse hyphen runs the way an upstream canonical name does."""
    return re.sub(r"-{2,}", "-", value)


def _hyphen_restoring_host_projects(name_project: str, record: dict[str, Any] | None) -> list[str]:
    """Return the record's own runtime project when its name confirms it.

    Upstream canonical names collapse hyphen runs, so an internationalised
    project like ``xn--9s9h`` reaches us as the record name
    ``toolforge-xn-9s9h``. The collapse is lossy in that direction and cannot be
    undone from the name alone, which would leave every punycode project
    permanently unverifiable.

    The record's own runtime host still carries the lost hyphen, and requiring
    it to collapse back to exactly the name-derived project is what makes it
    admissible here rather than a mere hint: the host is not being trusted to
    name the project, it is being checked against the name that already does. A
    record naming one project while linking to another project's launcher or
    proxy fails that check, which is the case the strictness exists for.
    """
    if not name_project:
        return []
    target = _collapse_hyphens(name_project).casefold()
    return [
        project
        for project in runtime_host_project_names(record)
        if project.casefold() != name_project.casefold() and _collapse_hyphens(project).casefold() == target
    ]


def verified_toolforge_project_names(tool_name: str, record: dict[str, Any] | None = None) -> list[str]:
    """Return project aliases backed by explicit Toolforge project identity.

    Only a canonical ``toolforge-$PROJECT`` name names the project within the
    record itself. Runtime and administration URLs are deliberately excluded:
    a Toolhub record may link to another project's launcher, proxy, or creation
    interface. Registered source provenance is evaluated separately.

    The single exception is a runtime host that collapses back to the record's
    own name-derived project — see ``_hyphen_restoring_host_projects``. Callers
    without a record in hand may omit it and lose only that exception.
    """
    candidates: list[str] = []
    clean_tool_name = _clean_name(tool_name)
    if clean_tool_name.casefold().startswith("toolforge-"):
        name_project = clean_tool_name[len("toolforge-") :]
        candidates.append(name_project)
        candidates.extend(_hyphen_restoring_host_projects(name_project, record))
    return _dedupe_project_names(candidates)


def candidate_toolforge_project_names(tool_name: str, record: dict[str, Any] | None) -> list[str]:
    """Return runtime-host project hints that are insufficient for verification."""
    source = record if isinstance(record, dict) else {}
    candidates = []
    for key in ("url", "api_url"):
        parsed = urlparse(str(source.get(key) or "").strip())
        host = (parsed.hostname or "").casefold()
        if host.endswith(".toolforge.org"):
            candidates.append(host.removesuffix(".toolforge.org"))
        if host == TOOLSADMIN_HOST:
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            for index in range(len(parts) - 2):
                if parts[index : index + 2] == ["tools", "id"]:
                    candidates.append(parts[index + 2])
                    break
    verified = {name.casefold() for name in verified_toolforge_project_names(tool_name, source)}
    return [name for name in _dedupe_project_names(candidates) if name.casefold() not in verified]


def runtime_host_project_names(record: dict[str, Any] | None) -> list[str]:
    """Return every project a record's own URLs could be served from.

    Deliberately generous about host form. Toolforge has served tools under
    ``$PROJECT.toolforge.org``, the legacy ``tools.wmflabs.org/$PROJECT`` path,
    and Cloud proxy subdomains, and a record written in one era still names its
    tool in that era's form. Reading only the current form would treat a
    decade-old URL as if it named no project at all.

    The breadth is safe only because of how this is used: it narrows a member
    set some other proof already established, so a wrong guess can withhold an
    edge but never invent one. It names the projects a tool *might* run in,
    never the one it provably runs in — that is
    ``verified_toolforge_project_names``, and it stays deliberately strict.
    """
    source = record if isinstance(record, dict) else {}
    candidates: list[str] = []
    for key in ("url", "api_url"):
        parsed = urlparse(str(source.get(key) or "").strip())
        host = (parsed.hostname or "").casefold()
        if host in LEGACY_TOOLFORGE_PATH_HOSTS:
            candidates.extend(_path_parts(parsed.geturl())[:1])
            continue
        for suffix in RUNTIME_HOST_SUFFIXES:
            if host.endswith(suffix):
                candidates.append(host.removesuffix(suffix))
                break
    return _dedupe_project_names(candidates)


def toolforge_project_names(tool_name: str, record: dict[str, Any] | None) -> list[str]:
    """Return all project associations, with deterministic aliases first."""
    return _dedupe_project_names(
        [
            *verified_toolforge_project_names(tool_name, record),
            *candidate_toolforge_project_names(tool_name, record),
        ]
    )


def names_by_toolforge_project(s: Session) -> dict[str, tuple[str, ...]]:
    """Index canonical Toolhub names by deterministically verified project."""
    index: dict[str, set[str]] = {}
    rows = s.execute(select(CanonicalToolCache.tool_name, CanonicalToolCache.record)).all()
    for tool_name, record in rows:
        for project in verified_toolforge_project_names(tool_name, record):
            index.setdefault(project.casefold(), set()).add(tool_name)
    return {
        project: tuple(sorted(tool_names, key=lambda value: (value.casefold(), value)))
        for project, tool_names in index.items()
    }


def candidate_names_by_toolforge_project(s: Session) -> dict[str, tuple[str, ...]]:
    """Index Toolhub names by URL-only project hints for unverified display."""
    index: dict[str, set[str]] = {}
    rows = s.execute(select(CanonicalToolCache.tool_name, CanonicalToolCache.record)).all()
    for tool_name, record in rows:
        for project in candidate_toolforge_project_names(tool_name, record):
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


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so a query for "100%" is not a match-anything pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_terms(query: str) -> list[str]:
    """Split a free-text query into the terms a row has to contain, all of them.

    One shared reading of a query, because there were two before and both were
    the same mistake: the entire string went into a single `LIKE %...%`, so a
    match had to contain the words *contiguously*. `lupin popups` found nothing
    while `lupin` and `popups` each found plenty, and since `_search_text` joins
    name, title and description with newlines, no query spanning two of those
    fields could ever match at all. Two-word queries are the ordinary case here
    -- the MCP tool description asks callers for exactly that shape.
    """
    return list(dict.fromkeys(part for part in str(query or "").casefold().split() if part))[:MAX_SEARCH_TERMS]


def search_predicate(query: str) -> ColumnElement[bool] | None:
    """AND one `search_text` substring test per term; None when there is no query.

    AND rather than the scored OR the MCP tool advertises, because ranking does
    not exist yet: `search_payload` falls through to ordering by tool name. An
    OR with no scorer behind it would answer "wikipedia bot" with a thousand
    alphabetical tools over 53,000 rows, most of them matching only
    "wikipedia", which is a worse answer than the empty one this replaces. Narrowing is the honest behaviour to ship
    without a scorer, and the tool descriptions now say so.
    """
    terms = search_terms(query)
    if not terms:
        return None
    return and_(*(CanonicalToolCache.search_text.like(f"%{escape_like(term)}%", escape="\\") for term in terms))


def _merge_listing_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Apply listing fields without erasing richer detail-only metadata."""
    merged = dict(existing)
    for key, value in incoming.items():
        if _has_value(value) or key not in merged:
            merged[key] = value
    return merged


def _queue_reconciliation(changed_names: list[str], *, enabled: bool) -> None:
    """Queue reconciliation for the records whose content actually moved.

    Called only after the canonical transaction succeeds. Processing is
    asynchronous so anonymous API requests do not wait on derived indexes.

    Reconciliation reads `record` and nothing else about the row, so an
    unchanged record rebuilds byte-identical edges and the freshness columns
    `upsert_records` also writes are invisible to it. Queueing every fetched
    name instead made a recovery snapshot -- which re-reads the whole catalog
    and finds it unchanged -- cost one queue entry per tool: generations 44
    through 49 each staged 4,501 records and retired none of them, pinning a
    lane that drains 25 a minute at its ceiling for hours.
    """
    if not enabled or not changed_names:
        return
    from backend.people_reconcile import enqueue_tool_names  # noqa: PLC0415 - avoid backend startup cycles.

    enqueue_tool_names(changed_names, reason="canonical_fetch")


def _next_record(row: CanonicalToolCache, record: dict[str, Any], *, detail: bool) -> tuple[dict[str, Any], bool]:
    """Return the record to store and whether it differs from the stored one.

    A row seen for the first time always reports a move: it has no stored
    record, and the merged one is never empty because a record without a usable
    name is dropped before it reaches here.
    """
    previous = row.record if isinstance(row.record, dict) else None
    merged = record if detail else _merge_listing_record(row.record or {}, record)
    return merged, previous != merged


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
    changed_names: list[str] = []
    try:
        with db.session_scope() as s:
            for name, record in clean_records:
                row = s.get(CanonicalToolCache, name)
                existing_is_detail = bool(row and is_tool_detail_url(row.source_url))
                if row is None:
                    row = CanonicalToolCache(tool_name=name)
                    s.add(row)
                merged_record, moved = _next_record(row, record, detail=detail)
                if moved:
                    changed_names.append(name)
                # search_text follows automatically: the model derives it from
                # every `record` assignment (see CanonicalToolCache).
                row.record = merged_record
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
    _queue_reconciliation(changed_names, enabled=enqueue_reconciliation)
    return len(clean_records)


def _prune_superseded(s: Session, generation: int) -> list[str]:
    """Delete official rows an older generation left behind, and name them.

    Scoped to official rows because upstream absence is only authoritative for
    rows that came from upstream. The table also holds records this codebase
    synthesizes from public wiki data -- a gadget a wiki declares is a real
    tool, but no official snapshot has an opinion about it. Pruning on
    generation alone would read the snapshot's silence as a deletion and erase
    every synthesized entry each time the catalog syncs.
    """
    superseded = (CanonicalToolCache.source == SOURCE_OFFICIAL, CanonicalToolCache.generation != generation)
    retired = list(
        s.execute(
            select(CanonicalToolCache.tool_name).where(*superseded).order_by(CanonicalToolCache.tool_name)
        ).scalars()
    )
    if retired:
        s.execute(delete(CanonicalToolCache).where(*superseded))
    return retired


def prune_completed_generation(s: Session, generation: int, expected_count: int) -> list[str]:
    """Delete names absent from one fully validated official catalog snapshot.

    A partial or internally inconsistent generation raises without deleting
    anything. This is the same safety boundary used by the account projection:
    upstream absence is authoritative only after every page agrees on the
    snapshot size.
    """
    observed = int(
        s.scalar(
            select(func.count())
            .select_from(CanonicalToolCache)
            .where(CanonicalToolCache.source == SOURCE_OFFICIAL, CanonicalToolCache.generation == generation)
        )
        or 0
    )
    if observed != expected_count:
        msg = f"catalog generation {generation} saw {observed} distinct rows, expected {expected_count}"
        raise ValueError(msg)
    return _prune_superseded(s, generation)


def stage_snapshot_records(records: list[dict[str, Any]], *, source_url: str, generation: int) -> int:
    """Persist a full-snapshot page without mutating the published catalog."""
    clean: dict[str, dict[str, Any]] = {}
    for record in records:
        name = _clean_name(record.get("name")) if isinstance(record, dict) else ""
        if name and name not in clean:
            clean[name] = record
    if not clean:
        return 0
    with db.session_scope() as session:
        for name, record in clean.items():
            session.merge(
                CatalogSnapshotStage(
                    generation=generation,
                    tool_name=name,
                    record=record,
                    source_url=source_url[:MAX_SOURCE_URL],
                    staged_at=utcnow(),
                )
            )
    return len(clean)


def discard_snapshot_stage(generation: int) -> None:
    with db.session_scope() as session:
        session.execute(delete(CatalogSnapshotStage).where(CatalogSnapshotStage.generation == generation))


def publish_snapshot_stage(s: Session, generation: int, expected_count: int) -> list[str]:
    """Replace the published generation atomically after exact-count validation."""
    staged = list(
        s.execute(
            select(CatalogSnapshotStage)
            .where(CatalogSnapshotStage.generation == generation)
            .order_by(CatalogSnapshotStage.tool_name)
        ).scalars()
    )
    if len(staged) != expected_count:
        msg = f"catalog generation {generation} staged {len(staged)} distinct rows, expected {expected_count}"
        raise ValueError(msg)
    now = utcnow()
    fresh = SEARCH_FRESH_SECONDS
    for item in staged:
        row = s.get(CanonicalToolCache, item.tool_name)
        existing_is_detail = bool(row and is_tool_detail_url(row.source_url))
        if row is None:
            row = CanonicalToolCache(tool_name=item.tool_name)
            s.add(row)
        row.record = _merge_listing_record(row.record or {}, item.record)
        if not existing_is_detail:
            row.source_url = item.source_url
            row.expires_at = now + timedelta(seconds=fresh)
            row.stale_until = now + timedelta(seconds=fresh + STALE_IF_ERROR_SECONDS)
        row.source = SOURCE_OFFICIAL
        row.sync_status = SYNC_OFFICIAL
        row.fetched_at = now
        row.generation = generation
    retired = _prune_superseded(s, generation)
    s.execute(delete(CatalogSnapshotStage).where(CatalogSnapshotStage.generation == generation))
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


def backfill_read_projection(*, batch_size: int = 500) -> int:
    """Populate compact card JSON and indexed modification timestamps once."""
    with db.session_scope() as session:
        if session.get(ApiCacheMeta, READ_PROJECTION_META_KEY) is not None:
            return 0
    filled = 0
    while True:
        with db.session_scope() as session:
            rows = list(
                session.execute(
                    select(CanonicalToolCache)
                    .where(CanonicalToolCache.card_record.is_(None))
                    .order_by(CanonicalToolCache.tool_name)
                    .limit(max(1, batch_size))
                ).scalars()
            )
            if not rows:
                marker = session.get(ApiCacheMeta, READ_PROJECTION_META_KEY)
                # Only a concurrent backfill can publish this marker between
                # the initial guard and this empty-page check.
                if marker is None:  # pragma: no branch - benign concurrent winner
                    session.add(ApiCacheMeta(key=READ_PROJECTION_META_KEY, value="complete"))
                return filled
            for row in rows:
                row.record = row.record or {}
                filled += 1


def backfill_status_flags(*, batch_size: int = 500) -> int:
    """Derive `deprecated` and `experimental` for rows written before the columns.

    No meta marker, unlike `backfill_read_projection`: the column is its own
    cursor, because NULL is exactly "this row predates the column". That makes
    the pass idempotent and resumable for free, and it cannot be marked complete
    while rows are still unfilled -- which a marker written next to a partial
    batch can be.

    Reassigning `record` is what fills them. The `@validates` hook on that
    attribute is the single definition of every derived column, so touching the
    source is how a backfill stays honest; computing the flags here would be a
    second definition to keep in step with the first.

    Short batches, and a refused one stops the pass rather than the deploy. This
    runs from `migrate.py`, where an uncaught error aborts after the host has
    already pulled, and it walks the whole catalogue against a sync job that
    writes the same table every few minutes. Stopping is safe precisely because
    the cursor is the data: whatever is still NULL is picked up next deploy, and
    the read path already treats NULL as "not flagged".
    """
    filled = 0
    while True:
        try:
            with db.session_scope() as session:
                rows = list(
                    session.execute(
                        select(CanonicalToolCache)
                        .where(CanonicalToolCache.deprecated.is_(None))
                        .order_by(CanonicalToolCache.tool_name)
                        .limit(max(1, batch_size))
                    ).scalars()
                )
                if not rows:
                    return filled
                for row in rows:
                    row.record = row.record or {}
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


def search(
    query: str = "",
    *,
    limit: int = MAX_SEARCH_RESULTS,
    include_archived: bool = False,
    statuses: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Search cached canonical records locally with simple deterministic matching.

    Filtering and limiting happen in SQL. Reading the whole table to keep at
    most `limit` rows meant transferring every cached record's JSON — the full
    catalog — for a query that returns a page of results.

    Archived tools are withheld by default, taken from `catalog_facets`'
    definition of the default population rather than a second copy of it. This
    browse path is what `cachedCanonicalTools` falls back to when the catalog
    search request fails, and a fallback that widened the population would have
    shown the reader a set the live page never offers: on meta alone the census
    files 1,874 archived user scripts against 729 active ones, so an outage
    would have answered a search with mostly tools nobody loads. Fetching by
    name is unaffected -- asking for a row by name is asking for it on purpose.
    """
    predicate = search_predicate(query)
    capped = max(1, min(MAX_SEARCH_RESULTS, int(limit or MAX_SEARCH_RESULTS)))
    population = select(CanonicalToolCache) if include_archived else catalog_facets.default_population()
    statement = population.order_by(CanonicalToolCache.fetched_at.desc(), CanonicalToolCache.tool_name)
    status = catalog_facets.status_predicate(catalog_facets.STATUS_VALUES if statuses is None else statuses)
    if status is not None:
        statement = statement.where(status)
    if predicate is not None:
        statement = statement.where(predicate)
    with db.session_scope() as s:
        rows = list(s.execute(statement.limit(capped)).scalars())
    return [_payload(row) for row in rows]


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
