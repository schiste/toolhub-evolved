# SPDX-License-Identifier: GPL-3.0-or-later
"""Filling in when each user script page was actually created.

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

Only page metadata is read: a title and the oldest revision timestamp. The
`revision` table also carries actor ids and edit comments, and this module has
no business with either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend import db, wiki_replica
from backend.models import UserScriptPage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

# Rows stamped per transaction. The write is one small string per row, so the
# batch is about bounding how long a single transaction holds the table rather
# than about how much work fits in memory.
BATCH: int = 500


def pending(session: Session, wiki: str, after: int) -> tuple[UserScriptPage, ...]:
    """Read the next batch of one wiki's pages that still have no creation date."""
    return tuple(
        session.query(UserScriptPage)
        .filter(
            UserScriptPage.wiki == wiki,
            UserScriptPage.created_at_wiki == "",
            UserScriptPage.id > after,
        )
        .order_by(UserScriptPage.id)
        .limit(BATCH)
        .all()
    )


def apply_dates(rows: Sequence[UserScriptPage], dates: dict[str, str]) -> int:
    """Stamp every row the replica had a date for. Returns how many were stamped."""
    written = 0
    for row in rows:
        stamp = dates.get(wiki_replica.normalize_title(row.title))
        if not stamp:
            continue
        row.created_at_wiki = stamp
        written += 1
    return written


def record(wiki: str, dates: dict[str, str]) -> int:
    """Write `dates` onto every page of one wiki that is still missing one.

    Paged by id, not by re-asking what is still blank. A page the replica has no
    row for -- deleted since the sweep saw it, or moved -- stays blank forever,
    and would come back in every batch of a "what is still missing" loop; the
    loop would then never end. Advancing past the last id seen cannot repeat.
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
    """Fill in creation dates for each wiki, if its replica can be reached.

    Best effort by construction. No `replica.my.cnf`, an unreachable replica, or
    a wiki `meta_p` has never heard of is zero rows written and no exception --
    per `backend.job_contract`, a source that was unavailable for one run is an
    observation rather than a job failure, and the census this runs after has
    already done its real work by the time it gets here.
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
            dates = wiki_replica.creation_dates_for(dbname, user=user, connect=connect)
        except Exception:  # noqa: BLE001, S112 - one wiki's outage must not hide the others
            continue
        written[wiki] = record(wiki, dates)
    return written
