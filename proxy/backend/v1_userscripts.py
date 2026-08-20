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
    """Describe what this wiki's directory is built from, and when it was last built.

    Two different ways of being partial are reported separately, because they
    have different remedies. `sweptAt` being empty says no full sweep has ever
    completed -- wait for one. `enumerated` being false says the wiki holds
    more script pages than one search pass can walk, so no amount of waiting
    will finish it; the enumeration itself has to be narrowed. Either way the
    counts below are a floor rather than a total.
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
    return {
        "wiki": wiki,
        "pages": pages,
        "sweepsCompleted": int(state.sweeps_completed) if state else 0,
        "sweptAt": common.iso(state.last_success_at) if state else "",
        "enumerated": bool(state.enumeration_complete) if state else True,
        "computedAt": common.iso(computed),
        "active": counts[directory.TIER_ACTIVE],
        "archive": counts[directory.TIER_ARCHIVE],
    }


def _entry(row: UserScriptDirectoryEntry) -> dict[str, Any]:
    """One directory entry, in the shape every endpoint here returns it."""
    return {
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
        wikis = sorted(
            set(s.execute(select(UserScriptCensusState.wiki)).scalars())
            | set(s.execute(select(UserScriptDirectoryEntry.wiki).distinct()).scalars())
        )
        results = [coverage(s, wiki) for wiki in wikis]
    return jsonify({"count": len(results), "results": results})


@v1_userscripts_bp.route("/v1/userscripts/directory/")
def v1_userscripts_directory() -> Response | tuple[Response, int]:
    """One tier of one wiki's directory, in its own ranked order."""
    if security.read_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
    wiki = str(request.args.get("wiki") or "").strip()
    if not wiki:
        return jsonify({"error": "wiki is required"}), 400
    tier = str(request.args.get("tier") or directory.TIER_ACTIVE).strip()
    if tier not in TIERS:
        return jsonify({"error": f"tier must be one of {list(TIERS)}"}), 400
    owner = str(request.args.get("owner") or "").strip()
    limit, offset = _limit(request.args.get("limit", "")), _offset(request.args.get("offset", ""))
    with db.session_scope() as s:
        where = [UserScriptDirectoryEntry.wiki == wiki, UserScriptDirectoryEntry.tier == tier]
        if owner:
            where.append(UserScriptDirectoryEntry.owner == owner)
        total = int(s.execute(select(func.count(UserScriptDirectoryEntry.id)).where(*where)).scalar() or 0)
        rows = s.execute(
            select(UserScriptDirectoryEntry)
            .where(*where)
            .order_by(UserScriptDirectoryEntry.position)
            .limit(limit)
            .offset(offset)
        ).scalars()
        results = [_entry(row) for row in rows]
        disclosed = coverage(s, wiki)
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


@v1_userscripts_bp.route("/v1/userscripts/script/")
def v1_userscripts_script() -> Response | tuple[Response, int]:
    """One script, with every page the collapse filed under it.

    The members are the point. An entry's instance count says a script was
    copied twelve times; the reviewer's next question is always *which twelve*,
    and whether each was filed because it is byte-identical or only because it
    shares a filename.
    """
    if security.read_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
    wiki = str(request.args.get("wiki") or "").strip()
    title = str(request.args.get("title") or "").strip()
    if not wiki or not title:
        return jsonify({"error": "wiki and title are required"}), 400
    with db.session_scope() as s:
        row = s.execute(
            select(UserScriptDirectoryEntry).where(
                UserScriptDirectoryEntry.wiki == wiki,
                UserScriptDirectoryEntry.title == title,
            )
        ).scalar_one_or_none()
        if row is None:
            # A page can be real and still have no entry: it folded onto another
            # script. Saying which one is more useful than a bare 404.
            member = s.execute(
                select(UserScriptDirectoryMember).where(
                    UserScriptDirectoryMember.wiki == wiki,
                    UserScriptDirectoryMember.title == title,
                )
            ).scalar_one_or_none()
            if member is None:
                return jsonify({"error": "no such script in this wiki's directory"}), 404
            return jsonify({"error": "not an original", "filedUnder": member.origin_title}), 404
        members = [
            {"title": member.title, "relation": member.relation}
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
