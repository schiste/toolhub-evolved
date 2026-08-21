# SPDX-License-Identifier: GPL-3.0-or-later
"""What each Toolhub list revision changed, and a day's worth of them as one row.

Upstream reports one recent-changes row per list revision and names no tool in
it: the comment is the bare string "Added tool to list".  The name is only in
the revision diff, which is a separate request, so it is resolved on a schedule
into `list_revision_changes` and read back from there while a page renders.

Grouping is kept apart from that lookup and needs no database at all, because
the recent feed already carries everything the key is made of.  That ordering
matters for cost: rows are collapsed first, so only the revisions behind one
rendered page are ever looked up, rather than every revision in the replica.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from backend import db, toolhub
from backend.models import ListRevisionChange, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable

# Upstream spells the list content type "toollist"; Evolved's own rows say
# "list".  Only upstream rows are ever grouped -- an Evolved row describes this
# site's own write and carries a client id no diff endpoint would recognize --
# but both are recognized so a stray spelling cannot slip past the check.
LIST_CONTENT_TYPES = {"list", "toollist"}
# A JSON Patch path into the tool array. "-" is the append position.
TOOLS_PATH = re.compile(r"^/tools/(?:\d+|-)$")
NAMING_OPERATIONS = {"add", "replace"}
DROPPING_OPERATIONS = {"remove", "replace"}
MAX_NAMES = 25
MAX_GROUP_REVISIONS = 100
DEFAULT_INGEST_LIMIT = 200
# Upstream is a volunteer-run service and this job is never urgent: one
# revision every quarter second is slow enough to be unnoticeable there and
# still drains a full backlog inside a minute.
REQUEST_PAUSE_SECONDS = 0.25
ERROR_LIMIT = 2000
REASON_NO_PARENT = "no_parent_revision"
REASON_NO_TOOL_CHANGE = "no_tool_change"
REASON_UNREADABLE = "unreadable_diff"


def _is_list_row(row: Any) -> bool:  # noqa: ANN401 - untrusted activity JSON
    """Return whether one activity row is an upstream Toolhub list revision.

    An Evolved row is excluded even though it is a list row.  It records this
    site's own write, carries a client id no diff endpoint would recognize, and
    already says in its comment what it did -- and collapsing two of them would
    silently drop one write from the feed.
    """
    if not isinstance(row, dict) or row.get("_evolved") is True:
        return False
    return str(row.get("content_type") or "").strip().lower() in LIST_CONTENT_TYPES


def _utc_day(value: Any) -> str:  # noqa: ANN401 - untrusted activity JSON
    """Return the UTC calendar day a revision belongs to, as an ISO date."""
    raw = str(value or "").strip()
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        # An unreadable stamp groups with nothing but itself. Merging two days
        # into one row is a wrong statement about history; a duplicate row is
        # only a redundant one.
        return f"unparsed:{raw}"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).date().isoformat()


def _editor(row: dict[str, Any]) -> str:
    user = row.get("user")
    if isinstance(user, dict):
        return str(user.get("id") or user.get("username") or "").strip()
    return str(user or "").strip()


def group_list_activity(rows: object) -> list[dict[str, Any]]:
    """Collapse each list's revisions into one row per editor per UTC day.

    The editor is part of the key because the Recent table has a "Last updated
    by" column: folding two people's edits into one row would put one of their
    names on the other's work.  The day boundary is the calendar day in UTC, so
    two edits four minutes apart across midnight stay two rows -- a coarser
    "within N hours" rule would group them, but no reader could then say what
    any given row covers.

    Rows arrive newest first, so the row a group keeps -- and therefore the
    timestamp it shows -- is its most recent revision.
    """
    if not isinstance(rows, list):
        return []
    grouped: list[dict[str, Any]] = []
    position_by_key: dict[tuple[str, str, str], int] = {}
    for row in rows:
        if not _is_list_row(row):
            grouped.append(row)
            continue
        key = (str(row.get("content_id") or ""), _editor(row), _utc_day(row.get("timestamp")))
        position = position_by_key.get(key)
        revision_id = row.get("id")
        identifiers = [revision_id] if isinstance(revision_id, int) else []
        if position is None:
            position_by_key[key] = len(grouped)
            grouped.append({**row, "revisionIds": identifiers})
            continue
        collapsed = grouped[position]
        if identifiers and len(collapsed["revisionIds"]) < MAX_GROUP_REVISIONS:
            collapsed["revisionIds"].extend(identifiers)
    return grouped


def _changes_by_revision(revision_ids: list[int]) -> dict[int, tuple[list[str], list[str]]]:
    if not revision_ids:
        return {}
    try:
        with db.session_scope() as session:
            stored = session.query(ListRevisionChange).filter(ListRevisionChange.revision_id.in_(revision_ids)).all()
            return {row.revision_id: (list(row.added or []), list(row.removed or [])) for row in stored}
    except SQLAlchemyError:
        # An enrichment nobody can read costs the reader a tool name, not the
        # page. The generic upstream comment is still rendered underneath.
        return {}


def _net_change(
    revision_ids: list[int], changes: dict[int, tuple[list[str], list[str]]]
) -> tuple[list[str], list[str]]:
    """Fold one day's revisions into what actually changed by the end of it.

    A tool added and then removed the same day is reported in neither column --
    and neither is one removed and then put back.  The day left the list exactly
    as it found it, and "added Foo, removed Foo" would describe the editing
    session rather than the list.  So the fold is a running tally per name
    rather than two sets: only a name the day left on a different footing than
    it found it survives.
    """
    tally: dict[str, int] = {}
    first_mention: dict[str, None] = {}
    for revision_id in revision_ids:
        entry = changes.get(revision_id)
        if entry is None:
            continue
        for direction, names in ((1, entry[0]), (-1, entry[1])):
            for name in names:
                tally[name] = tally.get(name, 0) + direction
                first_mention.setdefault(name, None)
    added = [name for name in first_mention if tally[name] > 0]
    removed = [name for name in first_mention if tally[name] < 0]
    return added[:MAX_NAMES], removed[:MAX_NAMES]


def attach_tool_changes(rows: object) -> list[dict[str, Any]]:
    """Name the tools each collapsed list row added or removed over its day."""
    if not isinstance(rows, list):
        return []
    wanted = [
        revision_id
        for row in rows
        if isinstance(row, dict)
        for revision_id in (row.get("revisionIds") or [])
        if isinstance(revision_id, int)
    ]
    changes = _changes_by_revision(wanted)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or "revisionIds" not in row:
            enriched.append(row)
            continue
        # Grouping walked the feed newest first; folding a day has to replay it
        # in the order the edits actually happened.
        added, removed = _net_change(list(reversed(row["revisionIds"])), changes)
        without_ids = {key: value for key, value in row.items() if key != "revisionIds"}
        enriched.append({**without_ids, "toolsAdded": added, "toolsRemoved": removed})
    return enriched


def _diff_operations(list_id: int, from_id: int, to_id: int) -> list[dict[str, Any]]:
    payload = toolhub.public_api_get(f"/api/lists/{list_id}/revisions/{from_id}/diff/{to_id}/", read_cache=False)
    operations = payload.get("operations") if isinstance(payload, dict) else None
    return [op for op in operations if isinstance(op, dict)] if isinstance(operations, list) else []


def _named_tools(operations: list[dict[str, Any]]) -> list[str]:
    """Return the tool names a patch introduces, in the order it applies them."""
    names: list[str] = []
    for operation in operations:
        if operation.get("op") not in NAMING_OPERATIONS:
            continue
        if not TOOLS_PATH.match(str(operation.get("path") or "")):
            continue
        value = operation.get("value")
        name = str((value.get("name") if isinstance(value, dict) else value) or "").strip()
        if name:
            names.append(name[:255])
    return names


def _drops_a_tool(operations: list[dict[str, Any]]) -> bool:
    return any(
        operation.get("op") in DROPPING_OPERATIONS and TOOLS_PATH.match(str(operation.get("path") or ""))
        for operation in operations
    )


def _store(
    revision_id: int,
    list_id: int,
    changed: tuple[list[str], list[str]],
    *,
    reason: str = "",
    error: str | None = None,
) -> None:
    added, removed = changed
    try:
        with db.session_scope() as session:
            session.merge(
                ListRevisionChange(
                    revision_id=revision_id,
                    list_id=list_id,
                    added=added[:MAX_NAMES],
                    removed=removed[:MAX_NAMES],
                    fetched_at=utcnow(),
                    reason=reason,
                    last_error=error[:ERROR_LIMIT] if error else None,
                )
            )
    except SQLAlchemyError:
        return


def resolve_revision(list_id: int, revision_id: int, parent_id: Any) -> str:  # noqa: ANN401 - untrusted JSON
    """Record which tools one revision added or removed, and return its reason.

    An addition carries its tool name in the forward diff.  A removal does not
    -- upstream emits a bare `{"op": "remove", "path": "/tools/12"}` -- so it is
    read from the reverse diff, where the same change appears as an addition and
    does carry the name.  That second request is made only when the forward diff
    actually drops something, which is why the ordinary case costs one request.
    """
    if not isinstance(parent_id, int):
        # The list's first revision has nothing to diff against. It created the
        # list rather than editing it, and upstream says so in the comment.
        _store(revision_id, list_id, ([], []), reason=REASON_NO_PARENT)
        return REASON_NO_PARENT
    try:
        forward = _diff_operations(list_id, parent_id, revision_id)
        added = _named_tools(forward)
        removed = _named_tools(_diff_operations(list_id, revision_id, parent_id)) if _drops_a_tool(forward) else []
    except Exception as exc:  # noqa: BLE001 - one unreadable diff must not end the run
        _store(revision_id, list_id, ([], []), reason=REASON_UNREADABLE, error=str(exc))
        return REASON_UNREADABLE
    reason = "" if added or removed else REASON_NO_TOOL_CHANGE
    _store(revision_id, list_id, (added, removed), reason=reason)
    return reason


def pending_revisions(rows: object, limit: int = DEFAULT_INGEST_LIMIT) -> list[tuple[int, int, Any]]:
    """Return replica list revisions never resolved before, newest id first."""
    candidates: dict[int, tuple[int, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not _is_list_row(row):
            continue
        revision_id, list_id = row.get("id"), row.get("content_id")
        if isinstance(revision_id, int) and isinstance(list_id, int):
            candidates.setdefault(revision_id, (list_id, row.get("parent_id")))
    if not candidates:
        return []
    known = _changes_by_revision(list(candidates))
    ordered = sorted((identifier for identifier in candidates if identifier not in known), reverse=True)
    return [(identifier, *candidates[identifier]) for identifier in ordered[:limit]]


def ingest(
    rows: object,
    *,
    limit: int = DEFAULT_INGEST_LIMIT,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Resolve every list revision in the replica that has no stored row yet.

    Newest first, so a backlog too large for one run still leaves the rows a
    reader is most likely to be looking at fully named.  Each revision is
    written whichever way it turns out -- named, uneventful, or unreadable --
    so the next run's anti-join skips it instead of retrying it forever.
    """
    pending = pending_revisions(rows, limit)
    counts = {"pending": len(pending), "named": 0, "uneventful": 0, "unreadable": 0}
    for index, (revision_id, list_id, parent_id) in enumerate(pending):
        if index:
            pause(REQUEST_PAUSE_SECONDS)
        reason = resolve_revision(list_id, revision_id, parent_id)
        if reason == REASON_UNREADABLE:
            counts["unreadable"] += 1
        elif reason:
            counts["uneventful"] += 1
        else:
            counts["named"] += 1
    return counts
