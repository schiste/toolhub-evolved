# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a wiki's stored census into the directory it exists to produce.

The sweep answers "what pages are there and what do they load". That is an
observation, and on frwiki it is 9,919 pages -- most of them personal skin slots
that nobody can reuse, and hundreds of them the same script written down twice.
This module answers the question a directory is actually asked: *how many
distinct scripts are there, who uses each one, and which of them is a candidate
to become a gadget.*

Everything here is derived. `backend.userscript_directory` already decides what
a distinct script is; this module's whole job is to hand it the corpus in the
form it wants, and to write down what it concluded. Nothing in it may become a
second opinion about the collapse -- if a rule needs changing it changes there,
where it is tested against the pilot's measured numbers.

Two decisions are made here rather than there, because they are about the
database and not about the directory:

*Demand is counted in people.* `rank_by_demand` counts distinct entries in the
source set it is given, and this module fills that set with usernames rather
than page titles. Somebody who loads a script from both `common.js` and
`vector.js` is one user of it; counting the two pages would report a script as
twice as popular as it is, and the whole point of the ranking is to find what
enough *people* use to be worth promoting.

*Creation order comes from `discovery_rank`, not from a timestamp.* The
collapse's "earliest page wins" rule only ever compares two pages, and the
search index hands enumeration order over for free, while asking the API for
9,919 creation dates is 9,919 requests. The rank is zero-padded into a string
because that is the ordering key `Candidate` takes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_

from backend import db, userscripts
from backend import userscript_directory as directory
from backend.models import (
    UserScriptDirectoryEntry,
    UserScriptDirectoryMember,
    UserScriptImport,
    UserScriptPage,
    utcnow,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

RELATION_ORIGINAL = "original"
RELATION_COPY = "copy"
RELATION_VARIANT = "variant"

# A Candidate's sort key is compared as a plain string, and within one wiki some
# pages carry a real creation timestamp while others carry nothing -- the
# replica the dates come from is absent outside Toolforge, and a page deleted
# between the sweep and the stamp never gets one at all. A MediaWiki timestamp
# is 14 digits opening on a century, so a fallback key of the same width behind
# a leading 9 sorts after every real date: a page whose creation date is unknown
# cannot outrank a page whose date is known, and unknowns keep discovery order
# among themselves.
_UNKNOWN_CREATED_PREFIX = "9"
# Width of the zero-padded `discovery_rank` that follows it. A wiki with more
# script pages than this would sort wrongly rather than loudly, so it is far
# above the largest corpus we have seen: frwiki's is 9,919.
_RANK_WIDTH = 13


def _sort_key(rank: int) -> str:
    """Render a discovery rank as a stand-in for a creation date it sorts behind."""
    return f"{_UNKNOWN_CREATED_PREFIX}{max(0, rank):0{_RANK_WIDTH}d}"


def candidates(session: Session, wiki: str) -> list[directory.Candidate]:
    """Every page on one wiki that is eligible to be a script in the directory.

    Deleted pages are left out. A page the wiki no longer serves cannot be
    promoted to a gadget, and keeping it would let a script that no longer
    exists claim to be the original of the pages that copied it.

    A page is offered with the creation date the wiki reports, and falls back to
    discovery order only where `backend.userscript_creation_dates` has not been
    able to supply one.
    """
    rows = (
        session.query(UserScriptPage)
        .filter(
            UserScriptPage.wiki == wiki,
            UserScriptPage.role == userscripts.ROLE_SCRIPT,
            UserScriptPage.deleted_at.is_(None),
        )
        .all()
    )
    return [
        directory.Candidate(
            title=row.title,
            owner=row.owner,
            basename=row.basename,
            created=row.created_at_wiki or _sort_key(row.discovery_rank),
            fingerprint=row.fingerprint,
        )
        for row in rows
    ]


def demand(session: Session, wiki: str) -> dict[str, set[str]]:
    """Map each page of this wiki to the distinct people who load it.

    Selected by *target*, not by source wiki: an import stored against another
    wiki that points here is still somebody loading this page, and those
    cross-wiki edges are the strongest argument any script has for becoming a
    global gadget.

    A page loading itself is not demand for it. This is the common case rather
    than a curiosity -- a script that installs its own helper subpage would
    otherwise vote for itself.
    """
    rows = (
        session.query(UserScriptImport.source_title, UserScriptImport.target_title, UserScriptPage.owner)
        .outerjoin(
            UserScriptPage,
            and_(
                UserScriptPage.wiki == UserScriptImport.wiki,
                UserScriptPage.title == UserScriptImport.source_title,
            ),
        )
        .filter(
            UserScriptImport.target_title != "",
            UserScriptImport.target_wiki.in_(["", wiki]),
        )
        .all()
    )
    loads: dict[str, set[str]] = {}
    for source_title, target_title, owner in rows:
        if source_title == target_title:
            continue
        # The owner comes from the census row, which resolved it when the page's
        # namespace was known. A source with no census row -- and so no owner to
        # name -- stands for itself and still counts once.
        loads.setdefault(target_title, set()).add(owner or source_title)
    return loads


def _members(origin: directory.Origin) -> list[tuple[str, str]]:
    """Every page belonging to one script, paired with why it belongs."""
    return [
        (origin.original.title, RELATION_ORIGINAL),
        *[(page.title, RELATION_COPY) for page in origin.copies],
        *[(page.title, RELATION_VARIANT) for page in origin.variants],
    ]


def page_ids(session: Session, wiki: str) -> dict[str, int]:
    """Map every live page title on this wiki to the identity that outlives the rebuild.

    The collapse works in titles, because titles are what the evidence is made
    of -- a shared basename, a matching fingerprint. But the rows it produces are
    deleted and re-created on every run, so their own ids mean nothing outside
    the run that wrote them. Carrying the census id alongside is what lets
    anything else -- a link, a note, another table -- refer to a script and still
    be referring to the same script after the next projection.
    """
    rows = session.query(UserScriptPage.title, UserScriptPage.id).filter(
        UserScriptPage.wiki == wiki,
        UserScriptPage.deleted_at.is_(None),
    )
    return dict(rows)


def _write(
    session: Session,
    wiki: str,
    tiers: dict[str, list[directory.Origin]],
    scores: dict[str, int],
    now: datetime,
) -> dict[str, int]:
    """Replace this wiki's directory with the one just computed.

    Deleted and rewritten per wiki rather than updated in place. An entry that
    stops being an original leaves no row to update -- it is now a member of
    somebody else's -- so a merge would have to reason about disappearance, and
    the projection is cheap enough that it never has to.
    """
    identities = page_ids(session, wiki)
    for table in (UserScriptDirectoryEntry, UserScriptDirectoryMember):
        session.query(table).filter(table.wiki == wiki).delete(synchronize_session=False)
    for tier, origins in tiers.items():
        for position, origin in enumerate(origins, start=1):
            session.add(
                UserScriptDirectoryEntry(
                    wiki=wiki,
                    script_id=identities.get(origin.original.title),
                    title=origin.original.title,
                    owner=origin.original.owner,
                    basename=origin.original.basename,
                    tier=tier,
                    demand=scores[origin.original.title],
                    instances=origin.instances,
                    position=position,
                    computed_at=now,
                ),
            )
            for title, relation in _members(origin):
                session.add(
                    UserScriptDirectoryMember(
                        wiki=wiki,
                        script_id=identities.get(title),
                        origin_id=identities.get(origin.original.title),
                        title=title,
                        origin_title=origin.original.title,
                        relation=relation,
                        computed_at=now,
                    ),
                )
    return {tier: len(origins) for tier, origins in tiers.items()}


def project(wiki: str) -> dict[str, Any]:
    """Rebuild one wiki's directory from what the census has already stored.

    Whole-corpus and idempotent: running it twice over unchanged pages produces
    the same rows. It reads no wiki and makes no request, so it is cheap enough
    to run at the end of every sweep and keep the directory from ever describing
    a corpus that has moved on.
    """
    with db.session_scope() as session:
        pages = candidates(session, wiki)
        loads = demand(session, wiki)
        origins = directory.collapse(pages, loads)
        scores = {origin.original.title: score for origin, score in directory.rank_by_demand(origins, loads)}
        counts = _write(session, wiki, directory.by_tier(origins, loads), scores, utcnow())
    return {
        "wiki": wiki,
        "candidates": len(pages),
        "originals": sum(counts.values()),
        "active": counts.get(directory.TIER_ACTIVE, 0),
        "archive": counts.get(directory.TIER_ARCHIVE, 0),
    }
