# SPDX-License-Identifier: GPL-3.0-or-later
"""Filling in when each gadget's code was first written, and by whom.

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

That same revision is also the only claim a wiki makes about who wrote the
gadget. A gadget's title names a namespace, not a person -- `MediaWiki:Gadget-HotCat.js`
belongs to the wiki -- and the definition line that declares it names nobody
either, so before this the catalogue published gadget records with no author at
all. The person who created the oldest of a gadget's code pages is the closest
thing to an author the wiki has, and it comes back on the row that already
dates it.

Only page metadata is read: a title, the oldest revision's timestamp, and the
name signed to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend import db, wiki_replica
from backend.models import WikiGadget

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


def earliest(pages: Sequence[str], origins: Mapping[str, wiki_replica.PageOrigin]) -> wiki_replica.PageOrigin:
    """Return the first revision of the oldest of a gadget's declared pages.

    Blank when the replica knew none of them, which is the ordinary answer for
    a gadget whose code lives on another wiki and is loaded from here. MediaWiki
    timestamps are fixed-width `YYYYMMDDHHMMSS`, so the oldest is the smallest
    string and no parsing is needed to find it.

    The whole revision rather than its date, so the name that comes back is the
    name on the edit that produced the date. Picking the oldest page and then
    looking its author up separately would be the same two lookups with one more
    chance of disagreeing.
    """
    found = [origin for page in pages if (origin := origins.get(page_key(page))) and origin.stamp]
    return min(found, key=lambda origin: origin.stamp) if found else wiki_replica.PageOrigin("", "")


def pending(session: Session, wiki: str, after: int) -> tuple[WikiGadget, ...]:
    """Read the next batch of one wiki's gadgets, in id order."""
    return tuple(
        session.query(WikiGadget)
        .filter(WikiGadget.wiki == wiki, WikiGadget.id > after)
        .order_by(WikiGadget.id)
        .limit(BATCH)
        .all()
    )


def apply_origins(rows: Sequence[WikiGadget], origins: Mapping[str, wiki_replica.PageOrigin]) -> int:
    """Stamp every row whose declared pages the replica knew. Returns how many moved.

    Unlike a user script page, a gadget's declaration can change under us: a
    later edit can add a file older than any it had before, and the honest
    creation date moves earlier with it. So a stamp is written when the row has
    none *or* when the computed one is older, never when it is newer. That rule
    only ever moves a date backwards, so it settles instead of oscillating with
    every re-read of the definition.

    The author travels with the date, because they describe one edit. When the
    date moves back to an older page, the credit moves to whoever wrote that
    page. Otherwise a name is written only onto a row whose stored date the
    computed one still matches -- which is how every gadget already in the table
    acquires an author, having been stamped before this lane read one.

    That match is a condition and not a formality. A declaration that drops its
    oldest file leaves a row whose date came from a page no longer declared, and
    the rule above deliberately does not move that date later. The earliest
    remaining page would then supply a name for an edit it was not: the gadget
    keeps its date and stays unattributed, which is the truthful pair.
    """
    written = 0
    for row in rows:
        origin = earliest(row.pages or (), origins)
        if not origin.stamp:
            continue
        if not row.created_at_wiki or origin.stamp < row.created_at_wiki:
            row.created_at_wiki = origin.stamp
            row.first_author_wiki = origin.author
            written += 1
            continue
        if origin.stamp == row.created_at_wiki and origin.author and not row.first_author_wiki:
            row.first_author_wiki = origin.author
            written += 1
    return written


def record(wiki: str, origins: Mapping[str, wiki_replica.PageOrigin]) -> int:
    """Write creation dates and authors onto one wiki's gadgets. Returns how many moved.

    Paged by id rather than by re-asking which rows are still blank. A gadget
    whose code the replica has no row for -- deleted, or living on another wiki
    -- stays blank, and would come back in every batch of a "what is missing"
    loop, which would then never end.
    """
    if not origins:
        return 0
    written = 0
    after = 0
    while True:
        with db.session_scope() as session:
            rows = pending(session, wiki, after)
            if not rows:
                return written
            after = rows[-1].id
            written += apply_origins(rows, origins)


def backfill(
    wikis: Sequence[str],
    *,
    connect: wiki_replica.Connect = wiki_replica.open_connection,
    known: Mapping[str, wiki_replica.Address] | None = None,
) -> dict[str, int]:
    """Fill in gadget creation dates for each wiki, if its replica can be reached.

    Best effort by construction, for the reasons `backend.userscript_creation_dates`
    gives: no `replica.my.cnf`, an unreachable replica, or a wiki `meta_p` has
    never heard of is zero rows written and no exception. The census this runs
    after has already read the definitions by the time it gets here.
    """
    user, addresses = wiki_replica.resolve(wikis, connect=connect, known=known)
    if user is None:
        return {}
    written: dict[str, int] = {}
    for wiki in wikis:
        address = addresses.get(wiki)
        if address is None:
            continue
        try:
            origins = wiki_replica.gadget_creation_origins_for(
                address.dbname, section=address.section, user=user, connect=connect
            )
        except Exception:  # noqa: BLE001, S112 - one wiki's outage must not hide the others
            continue
        written[wiki] = record(wiki, origins)
    return written
