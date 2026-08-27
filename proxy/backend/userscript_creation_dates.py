# SPDX-License-Identifier: GPL-3.0-or-later
"""Filling in when each user script page was created, and by whom.

The census learns a page's title, body and last edit from the API, but not its
birthday: `prop=revisions` will only walk a history oldest-first for one page at
a time (`rvdir=newer` with more than one title is `invalidparammix`), so asking
the API costs one request per page. Measured against frwiki that is ~2,000
requests and about an hour and a half for a corpus the Wiki Replicas answer in
roughly one second, from an index the replica already maintains.

So the date arrives on a different road from the rest of the page, and arrives
late: a page is stored the moment the sweep reads it, and its creation date is
stamped on afterwards, if a replica happens to be reachable. Everything
downstream is written to tolerate a blank -- `backend.userscript_directory`
falls back to discovery order -- because on a laptop, in CI, and on any host
without `replica.my.cnf` there is no replica and never will be.

The same row answers a second question for free. A page's oldest revision has
an author as well as a date, and that author is the person who wrote the script
-- not merely the person whose user space it sits in. The two usually agree and
sometimes do not: on fr.wikipedia 954 of 14,433 script pages were first written
by somebody other than their owner, most often an administrator installing a
script on a user's behalf. Both are kept, because `owner` says whose space a
page occupies and this says who put the code there.

Only page metadata is read: a title, the oldest revision's timestamp, and the
name signed to it. Edit comments the `revision` table also carries are read by
nothing here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_

from backend import db, wiki_replica
from backend.models import UserScriptPage

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session

# Rows stamped per transaction. The write is one small string per row, so the
# batch is about bounding how long a single transaction holds the table rather
# than about how much work fits in memory.
BATCH: int = 500


def pending(session: Session, wiki: str, after: int) -> tuple[UserScriptPage, ...]:
    """Read the next batch of one wiki's pages still missing a date or an author.

    Either, not both. Every page stored before this lane read authors already
    has its date, so a filter on the date alone would decide the whole corpus
    was settled and no existing page would ever be attributed. Asking for rows
    missing either field is what lets the same pass fill in the column behind
    it, and costs nothing once it has: a fully stamped wiki matches no rows.
    """
    return tuple(
        session.query(UserScriptPage)
        .filter(
            UserScriptPage.wiki == wiki,
            or_(UserScriptPage.created_at_wiki == "", UserScriptPage.first_author_wiki == ""),
            UserScriptPage.id > after,
        )
        .order_by(UserScriptPage.id)
        .limit(BATCH)
        .all()
    )


def apply_origins(rows: Sequence[UserScriptPage], origins: Mapping[str, wiki_replica.PageOrigin]) -> int:
    """Stamp every row the replica knew. Returns how many rows moved.

    Each field is written only where it is still empty, so a second pass over a
    stamped wiki is a no-op rather than a rewrite of every row with the same
    values -- a timestamps-only UPDATE is a lock wait that buys nothing. A row
    counts as moved if either field was filled, which is why a page that gains
    only an author still counts.
    """
    written = 0
    for row in rows:
        origin = origins.get(wiki_replica.normalize_title(row.title))
        if origin is None:
            continue
        moved = False
        if origin.stamp and not row.created_at_wiki:
            row.created_at_wiki = origin.stamp
            moved = True
        if origin.author and not row.first_author_wiki:
            row.first_author_wiki = origin.author
            moved = True
        written += moved
    return written


def record(wiki: str, origins: Mapping[str, wiki_replica.PageOrigin]) -> int:
    """Write `origins` onto every page of one wiki still missing part of one.

    Paged by id, not by re-asking what is still blank. A page the replica has no
    row for -- deleted since the sweep saw it, or moved -- stays blank forever,
    and would come back in every batch of a "what is still missing" loop; the
    loop would then never end. Advancing past the last id seen cannot repeat.
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
    """Fill in creation dates for each wiki, if its replica can be reached.

    Best effort by construction. No `replica.my.cnf`, an unreachable replica, or
    a wiki `meta_p` has never heard of is zero rows written and no exception --
    per `backend.job_contract`, a source that was unavailable for one run is an
    observation rather than a job failure, and the census this runs after has
    already done its real work by the time it gets here.
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
            origins = wiki_replica.creation_origins_for(
                address.dbname, section=address.section, user=user, connect=connect
            )
        except Exception:  # noqa: BLE001, S112 - one wiki's outage must not hide the others
            continue
        written[wiki] = record(wiki, origins)
    return written
