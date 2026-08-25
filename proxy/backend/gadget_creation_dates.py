# SPDX-License-Identifier: GPL-3.0-or-later
"""Filling in when each gadget's code was first written.

A definition page says which gadget a wiki offers today and nothing about when
it started. `MediaWiki:Gadgets-definition` has no history worth reading for this
-- the line for HotCat may have been rewritten a dozen times since 2007 -- and
`first_seen_at` on the inventory row records when this catalogue first read the
wiki, which for every gadget currently known is some afternoon in 2026.

The real answer is in the code pages. A gadget is declared as a set of files
under `MediaWiki:Gadget-`, and the oldest first revision among them is the
moment the gadget began to exist. That is one indexed query per wiki against
the Wiki Replicas -- a hundred-odd rows -- and it is asked on the same terms as
`backend.userscript_creation_dates`: best effort, after the census has done its
real work, and silently skipped wherever no replica can be reached.

Only page metadata is read: a title and the oldest revision timestamp.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend import db, wiki_replica
from backend.models import WikiGadget

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

# Rows per transaction. A wiki declares of the order of a hundred gadgets, so
# this bounds nothing in practice and exists so a wiki that one day declares ten
# thousand does not hold the table for the length of all of them.
BATCH: int = 500


def page_key(page: str) -> str:
    """Return the replica's `page_title` for one declared gadget file.

    A definition names its files bare -- `HotCat.js` -- while the page they live
    on is `MediaWiki:Gadget-HotCat.js`, stored as `Gadget-HotCat.js` with spaces
    folded to underscores. Only the namespace is stripped in storage, so the
    prefix is part of the key rather than part of the namespace.
    """
    return f"{wiki_replica.GADGET_TITLE_PREFIX}{page.strip().replace(' ', '_')}"


def earliest(pages: Sequence[str], dates: dict[str, str]) -> str:
    """Return the oldest creation stamp among a gadget's declared pages.

    Empty when the replica knew none of them, which is the ordinary answer for
    a gadget whose code lives on another wiki and is loaded from here. MediaWiki
    timestamps are fixed-width `YYYYMMDDHHMMSS`, so the oldest is the smallest
    string and no parsing is needed to find it.
    """
    found = [stamp for page in pages if (stamp := dates.get(page_key(page)))]
    return min(found) if found else ""


def pending(session: Session, wiki: str, after: int) -> tuple[WikiGadget, ...]:
    """Read the next batch of one wiki's gadgets, in id order."""
    return tuple(
        session.query(WikiGadget)
        .filter(WikiGadget.wiki == wiki, WikiGadget.id > after)
        .order_by(WikiGadget.id)
        .limit(BATCH)
        .all()
    )


def apply_dates(rows: Sequence[WikiGadget], dates: dict[str, str]) -> int:
    """Stamp every row whose declared pages the replica dated. Returns how many moved.

    Unlike a user script page, a gadget's declaration can change under us: a
    later edit can add a file older than any it had before, and the honest
    creation date moves earlier with it. So a stamp is written when the row has
    none *or* when the computed one is older, never when it is newer. That rule
    only ever moves a date backwards, so it settles instead of oscillating with
    every re-read of the definition.
    """
    written = 0
    for row in rows:
        stamp = earliest(row.pages or (), dates)
        if not stamp or (row.created_at_wiki and row.created_at_wiki <= stamp):
            continue
        row.created_at_wiki = stamp
        written += 1
    return written


def record(wiki: str, dates: dict[str, str]) -> int:
    """Write creation dates onto one wiki's gadgets. Returns how many moved.

    Paged by id rather than by re-asking which rows are still blank. A gadget
    whose code the replica has no row for -- deleted, or living on another wiki
    -- stays blank, and would come back in every batch of a "what is missing"
    loop, which would then never end.
    """
    if not dates:
        return 0
    written = 0
    after = 0
    while True:
        with db.session_scope() as session:
            rows = pending(session, wiki, after)
            if not rows:
                return written
            after = rows[-1].id
            written += apply_dates(rows, dates)


def backfill(
    wikis: Sequence[str],
    *,
    connect: wiki_replica.Connect = wiki_replica.open_connection,
) -> dict[str, int]:
    """Fill in gadget creation dates for each wiki, if its replica can be reached.

    Best effort by construction, for the reasons `backend.userscript_creation_dates`
    gives: no `replica.my.cnf`, an unreachable replica, or a wiki `meta_p` has
    never heard of is zero rows written and no exception. The census this runs
    after has already read the definitions by the time it gets here.
    """
    user = wiki_replica.credentials()
    if user is None:
        return {}
    try:
        dbnames = wiki_replica.dbnames_for(wikis, user=user, connect=connect)
    except Exception:  # noqa: BLE001 - an unreachable replica is not a failed census
        return {}
    written: dict[str, int] = {}
    for wiki in wikis:
        dbname = dbnames.get(wiki)
        if dbname is None:
            continue
        try:
            dates = wiki_replica.gadget_creation_dates_for(dbname, user=user, connect=connect)
        except Exception:  # noqa: BLE001, S112 - one wiki's outage must not hide the others
            continue
        written[wiki] = record(wiki, dates)
    return written
