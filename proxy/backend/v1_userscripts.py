# SPDX-License-Identifier: GPL-3.0-or-later
"""Public read-only endpoints over one wiki's user-script directory.

Everything here reads what `backend.userscript_projection` last wrote. Nothing
in this module decides what a distinct script is, ranks anything, or recounts
demand -- if an answer here disagrees with the directory, this module is wrong.

Every response carries the coverage of the wiki it answers for. A directory is
built from a census that has to crawl thousands of pages, so an empty or thin
answer usually means "this wiki has not been swept", not "this wiki has no user
scripts" -- and a reader who cannot tell those apart will draw exactly the wrong
conclusion from a quiet result.
"""

from datetime import datetime
from typing import Any

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import db, security
from backend import userscript_directory as directory
from backend import userscript_projection as projection
from backend import v1_common as common
from backend.models import (
    UserScriptCensusState,
    UserScriptDirectoryEntry,
    UserScriptDirectoryMember,
    UserScriptPage,
)

v1_userscripts_bp = Blueprint("v1_userscripts", __name__)

DEFAULT_LIMIT = 25
MAX_LIMIT = 200
TIERS = (directory.TIER_ACTIVE, directory.TIER_ARCHIVE)


def _limit(raw: str) -> int:
    """Clamp a caller's page size into [1, MAX_LIMIT], defaulting on nonsense."""
    try:
        return max(1, min(MAX_LIMIT, int(raw))) if raw else DEFAULT_LIMIT
    except ValueError:
        return DEFAULT_LIMIT


def _offset(raw: str) -> int:
    """Read a caller's offset; anything negative or unparseable starts at the beginning."""
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def coverage(s: Session, wiki: str) -> dict[str, Any]:
    """Describe what this wiki's directory is built from, and how current it is.

    Three timestamps, because a census can be stale in three unrelated ways and
    only one of them is about the job still running. `checkedAt` is liveness --
    the last run of any kind -- and it is the one that says nothing at all about
    the data, since a watch stamps it every hour whether the wiki moved or not.
    `sweptAt` is when this wiki's user space was last enumerated and walked, and
    `currentTo` is the wiki's own clock: how far into recent changes the watch
    has read. A directory can be an hour old by `checkedAt`, a month old by
    `sweptAt`, and current to a fortnight ago by `currentTo`, all at once, and a
    reader given only the first would call it fresh.

    Two ways of being partial are reported separately, because they have
    different remedies. `sweepsCompleted` at zero says no full sweep has ever
    finished -- wait for one. `enumerated` being false says the wiki holds more
    script pages than one search pass can walk, so no amount of waiting will
    finish it. `enumeratedBy` names the road behind the counts, which is what
    distinguishes an exact census from one that merely never hit a cap.
    """
    state = s.get(UserScriptCensusState, wiki)
    pages = int(
        s.execute(
            select(func.count(UserScriptPage.id)).where(
                UserScriptPage.wiki == wiki,
                UserScriptPage.deleted_at.is_(None),
            )
        ).scalar()
        or 0
    )
    counts = dict.fromkeys(TIERS, 0)
    for tier, total in s.execute(
        select(UserScriptDirectoryEntry.tier, func.count(UserScriptDirectoryEntry.id))
        .where(UserScriptDirectoryEntry.wiki == wiki)
        .group_by(UserScriptDirectoryEntry.tier)
    ):
        counts[tier] = int(total)
    computed = s.execute(
        select(func.max(UserScriptDirectoryEntry.computed_at)).where(UserScriptDirectoryEntry.wiki == wiki)
    ).scalar()
    return _coverage_row(wiki, state, pages, counts, computed)


def _coverage_row(
    wiki: str,
    state: UserScriptCensusState | None,
    pages: int,
    counts: dict[str, int],
    computed: datetime | None,
) -> dict[str, Any]:
    """Assemble one wiki's coverage from parts already read.

    Split out so the one-wiki reader and the whole-roster reader below cannot
    drift: they disagree about how to *fetch* the parts, and must not disagree
    about what a coverage record is.
    """
    return {
        "wiki": wiki,
        "pages": pages,
        "sweepsCompleted": int(state.sweeps_completed) if state else 0,
        "sweptAt": common.iso(state.last_started_at) if state else "",
        "currentTo": (state.changes_cursor or "") if state else "",
        "checkedAt": common.iso(state.last_success_at) if state else "",
        "enumerated": bool(state.enumeration_complete) if state else True,
        "enumeratedBy": (state.enumeration_source or "") if state else "",
        "computedAt": common.iso(computed),
        "active": counts.get(directory.TIER_ACTIVE, 0),
        "archive": counts.get(directory.TIER_ARCHIVE, 0),
    }


def _all_coverage(s: Session) -> list[dict[str, Any]]:
    """Every touched wiki's coverage, in a fixed number of queries.

    `coverage()` costs four queries, which is the right shape for one wiki and
    the wrong one for a thousand. This endpoint used to call it per wiki: at the
    three wikis the census was configured for that was twelve queries and nobody
    noticed, and across every Wikimedia project it is four thousand -- one of
    them a COUNT over a quarter-million-row table, per wiki. The endpoint stayed
    correct and grew to fourteen seconds, which is past the browser's read
    timeout, so the directory page stopped rendering at all.

    Grouping the same four reads costs four queries whatever the roster grows
    to. The wikis are still the union of "has census state" and "has directory
    entries", because a wiki can have been swept without projecting anything and
    a projection can outlive the state row that produced it.
    """
    states = {row.wiki: row for row in s.execute(select(UserScriptCensusState)).scalars()}
    pages = {
        wiki: int(total)
        for wiki, total in s.execute(
            select(UserScriptPage.wiki, func.count(UserScriptPage.id))
            .where(UserScriptPage.deleted_at.is_(None))
            .group_by(UserScriptPage.wiki)
        )
    }
    counts: dict[str, dict[str, int]] = {}
    for wiki, tier, total in s.execute(
        select(
            UserScriptDirectoryEntry.wiki,
            UserScriptDirectoryEntry.tier,
            func.count(UserScriptDirectoryEntry.id),
        ).group_by(UserScriptDirectoryEntry.wiki, UserScriptDirectoryEntry.tier)
    ):
        counts.setdefault(wiki, {})[tier] = int(total)
    # `.all()` rather than the Result itself: a Result carries `keys()`, so
    # `dict()` reads it as a mapping and fails instead of consuming the rows.
    computed = dict(
        s.execute(
            select(
                UserScriptDirectoryEntry.wiki,
                func.max(UserScriptDirectoryEntry.computed_at),
            ).group_by(UserScriptDirectoryEntry.wiki)
        ).all()
    )
    return [
        _coverage_row(wiki, states.get(wiki), pages.get(wiki, 0), counts.get(wiki, {}), computed.get(wiki))
        for wiki in sorted(set(states) | set(counts))
    ]


def _entry(row: UserScriptDirectoryEntry) -> dict[str, Any]:
    """One directory entry, in the shape every endpoint here returns it.

    `id` is the census page's identity, not the directory row's. The directory
    is rebuilt whole on every projection, so its row ids are renumbered on a
    schedule nobody outside this service can see; the page id is stable for as
    long as the page exists. A caller that stores one of these should store this
    one, which is why it is the only one disclosed.
    """
    return {
        "id": int(row.script_id) if row.script_id else 0,
        "wiki": row.wiki,
        "title": row.title,
        "owner": row.owner,
        "basename": row.basename,
        "tier": row.tier,
        "demand": int(row.demand),
        "instances": int(row.instances),
        "position": int(row.position),
    }


@v1_userscripts_bp.route("/v1/userscripts/wikis/")
def v1_userscripts_wikis() -> Response | tuple[Response, int]:
    """Every wiki the census has touched, with what it has so far."""
    if security.read_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
    with db.session_scope() as s:
        results = _all_coverage(s)
    return jsonify({"count": len(results), "results": results})


@v1_userscripts_bp.route("/v1/userscripts/directory/")
def v1_userscripts_directory() -> Response | tuple[Response, int]:
    """One tier of the directory: a single wiki's, or every wiki's at once.

    Omitting `wiki` asks for the whole census rather than one project, which is
    what an unqualified visit wants -- the directory covers 897 wikis holding
    entries, and no single one of them is the obvious place to start.

    The two are ranked by different columns because only one of them can be.
    `position` is a rank *within* a wiki, so every wiki has a row at position 1
    and ordering the union by it would interleave 897 unrelated ladders. Across
    wikis the order has to come from `demand` itself, with `wiki` and `title`
    breaking ties so that paging is stable rather than merely sorted.

    A cross-wiki row keeps its own `wiki`, so a caller can still follow any
    entry back to the project that publishes it; the same script name on two
    wikis stays two rows, because they are two scripts -- different code,
    different owner, different readers.
    """
    if security.read_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
    wiki = str(request.args.get("wiki") or "").strip()
    tier = str(request.args.get("tier") or directory.TIER_ACTIVE).strip()
    if tier not in TIERS:
        return jsonify({"error": f"tier must be one of {list(TIERS)}"}), 400
    owner = str(request.args.get("owner") or "").strip()
    limit, offset = _limit(request.args.get("limit", "")), _offset(request.args.get("offset", ""))
    with db.session_scope() as s:
        where = [UserScriptDirectoryEntry.tier == tier]
        if wiki:
            where.append(UserScriptDirectoryEntry.wiki == wiki)
        if owner:
            where.append(UserScriptDirectoryEntry.owner == owner)
        order = (
            [UserScriptDirectoryEntry.position]
            if wiki
            else [
                UserScriptDirectoryEntry.demand.desc(),
                # A tiebreak so paging is stable rather than merely sorted, and
                # `id` rather than anything meaningful because the index has to
                # carry it: (wiki, title) is 3068 bytes under utf8mb4 and puts
                # the key over MariaDB's limit. Descending like `demand`, since
                # one index is scanned in one direction and mixing the two would
                # put a filesort over the whole tier in front of every page.
                # Which row wins a tie is arbitrary either way -- what matters
                # is that it wins it the same way on every page of one reading.
                UserScriptDirectoryEntry.id.desc(),
            ]
        )
        total = int(s.execute(select(func.count(UserScriptDirectoryEntry.id)).where(*where)).scalar() or 0)
        rows = s.execute(
            select(UserScriptDirectoryEntry).where(*where).order_by(*order).limit(limit).offset(offset)
        ).scalars()
        results = [_entry(row) for row in rows]
        # A cross-wiki read has no single coverage record to disclose, and
        # inventing one by merging 897 of them here would duplicate what the
        # caller already holds from `/v1/userscripts/wikis/`. Say nothing rather
        # than say something averaged.
        disclosed = coverage(s, wiki) if wiki else None
    return jsonify(
        {
            "wiki": wiki,
            "tier": tier,
            "count": len(results),
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
            "coverage": disclosed,
        }
    )


def _script_id(raw: str) -> int:
    """Read a caller's script id; anything unparseable or non-positive is absent."""
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _asked_for(s: Session, script_id: int, wiki: str, title: str) -> tuple[Any, Any]:
    """Find the entry a caller named, or the member row explaining why there is none.

    Two ways in, and the identity is the better one. A title is what a reader
    has to hand, but it moves: a page renamed on the wiki is a different title
    for the same script, and a title reused after a deletion is the same title
    for a different one. The id is neither.
    """
    if script_id:
        where_entry = (UserScriptDirectoryEntry.script_id == script_id,)
        where_member = (UserScriptDirectoryMember.script_id == script_id,)
    else:
        where_entry = (UserScriptDirectoryEntry.wiki == wiki, UserScriptDirectoryEntry.title == title)
        where_member = (UserScriptDirectoryMember.wiki == wiki, UserScriptDirectoryMember.title == title)
    row = s.execute(select(UserScriptDirectoryEntry).where(*where_entry)).scalars().first()
    if row is not None:
        return (row, None)
    # A page can be real and still have no entry: it folded onto another script.
    # Saying which one is more useful than a bare 404.
    return (None, s.execute(select(UserScriptDirectoryMember).where(*where_member)).scalars().first())


@v1_userscripts_bp.route("/v1/userscripts/script/")
def v1_userscripts_script() -> Response | tuple[Response, int]:
    """One script, by identity or by title, with every page the collapse filed under it.

    The members are the point. An entry's instance count says a script was
    copied twelve times; the reviewer's next question is always *which twelve*,
    and whether each was filed because it is byte-identical or only because it
    shares a filename.
    """
    if security.read_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
    script_id = _script_id(str(request.args.get("id") or "").strip())
    wiki = str(request.args.get("wiki") or "").strip()
    title = str(request.args.get("title") or "").strip()
    if not script_id and not (wiki and title):
        return jsonify({"error": "id, or wiki and title, are required"}), 400
    with db.session_scope() as s:
        row, member = _asked_for(s, script_id, wiki, title)
        if row is None:
            if member is None:
                return jsonify({"error": "no such script in the directory"}), 404
            return jsonify(
                {
                    "error": "not an original",
                    "filedUnder": member.origin_title,
                    "filedUnderId": int(member.origin_id) if member.origin_id else 0,
                }
            ), 404
        wiki, title = row.wiki, row.title
        members = [
            {"id": int(member.script_id) if member.script_id else 0, "title": member.title, "relation": member.relation}
            for member in s.execute(
                select(UserScriptDirectoryMember)
                .where(
                    UserScriptDirectoryMember.wiki == wiki,
                    UserScriptDirectoryMember.origin_title == title,
                    UserScriptDirectoryMember.relation != projection.RELATION_ORIGINAL,
                )
                .order_by(UserScriptDirectoryMember.relation, UserScriptDirectoryMember.title)
            ).scalars()
        ]
        entry = _entry(row)
        disclosed = coverage(s, wiki)
    return jsonify({**entry, "members": members, "coverage": disclosed})
