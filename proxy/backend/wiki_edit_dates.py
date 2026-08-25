# SPDX-License-Identifier: GPL-3.0-or-later
"""Filling in when each wiki-hosted tool's source was last edited.

Both censuses already establish when a tool began -- `backend.userscript_creation_dates`
and `backend.gadget_creation_dates` stamp a first revision on every row they can
-- and neither has ever recorded when one last moved. That is the field a reader
actually uses. "Created 2009" says a script is old; it does not say whether it
still works, and a catalogue that can only answer the first question sorts a
gadget rewritten last week behind one abandoned a decade ago.

The date is asked for on the same terms as a creation date and by the same road,
because the alternative roads are worse for each lane in a different way:

  * A gadget census reads one page per wiki -- `MediaWiki:Gadgets-definition` is
    the whole inventory -- and never fetches the code. There is no API answer
    here to piggyback on, and asking for one would turn a one-request job into a
    hundred-title fetch on every tick.
  * A user-script sweep does fetch bodies, and does learn a last edit doing so.
    But it deliberately skips a page whose `page_latest` has not moved, which is
    the entire reason a second sweep is cheap, so the pages it can date are
    exactly the ones that were already dated. A page stored before this existed
    would wait for somebody to edit it.

One indexed query per wiki dates that wiki's whole corpus, under the same
best-effort contract the creation dates work under: no `replica.my.cnf`, an
unreachable replica, or a wiki `meta_p` has never heard of is zero rows written
and no exception raised. A deployment without a replica publishes no last-edit
date and is otherwise unchanged.

The two lanes keep separate entry points rather than sharing one that dates
everything. Each census runs over the wikis it was configured for, and those
lists are not the same list; a gadget census that also stamped script pages
would be silently doing the sweep's work on a schedule nobody chose for it.

Only page metadata is read: a title and its current revision's timestamp.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend import db, gadget_creation_dates, wiki_replica
from backend.models import UserScriptPage, WikiGadget

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session

# Rows per transaction, matching the creation-date lanes. The write is one short
# string per row, so this bounds how long a single transaction holds the table
# rather than how much fits in memory.
BATCH: int = 500


def latest(pages: Sequence[str], dates: dict[str, str]) -> str:
    """Return the newest edit stamp among a gadget's declared pages.

    A gadget is a set of files and any one of them being edited is the gadget
    being edited, so the newest wins where `gadget_creation_dates.earliest`
    takes the oldest. Empty when the replica knew none of them, which is the
    ordinary answer for a gadget whose code lives on another wiki. MediaWiki
    timestamps are fixed-width `YYYYMMDDHHMMSS`, so the newest is the largest
    string and no parsing is needed to find it.
    """
    found = [stamp for page in pages if (stamp := dates.get(gadget_creation_dates.page_key(page)))]
    return max(found) if found else ""


def _advance(current: str, stamp: str) -> bool:
    """Whether `stamp` is worth writing over `current`.

    Only ever forward, and never sideways. Forward because an edit date that
    moved back would mean the page's history had been rewritten under us, which
    the replica reporting a stale row looks exactly like. Never sideways because
    an assignment of the value a column already holds still writes the row: the
    census runs hourly over corpora in the tens of thousands, and a job that
    rewrote every one of them each tick to change nothing would hold locks
    against everything else touching the table for no result at all.
    """
    return bool(stamp) and stamp > current


def _stamp_gadgets(rows: Sequence[WikiGadget], dates: dict[str, str]) -> int:
    """Stamp every gadget whose declared pages the replica dated. Returns how many moved."""
    written = 0
    for row in rows:
        stamp = latest(row.pages or (), dates)
        if not _advance(row.touched_at_wiki, stamp):
            continue
        row.touched_at_wiki = stamp
        written += 1
    return written


def _stamp_scripts(rows: Sequence[UserScriptPage], dates: dict[str, str]) -> int:
    """Stamp every script page the replica dated. Returns how many moved."""
    written = 0
    for row in rows:
        stamp = dates.get(wiki_replica.normalize_title(row.title), "")
        if not _advance(row.touched_at_wiki, stamp):
            continue
        row.touched_at_wiki = stamp
        written += 1
    return written


def _pending_gadgets(session: Session, wiki: str, after: int) -> tuple[WikiGadget, ...]:
    """Read the next batch of one wiki's gadgets, in id order."""
    return tuple(
        session.query(WikiGadget)
        .filter(WikiGadget.wiki == wiki, WikiGadget.id > after)
        .order_by(WikiGadget.id)
        .limit(BATCH)
        .all()
    )


def _pending_scripts(session: Session, wiki: str, after: int) -> tuple[UserScriptPage, ...]:
    """Read the next batch of one wiki's script pages, in id order.

    Deleted pages come back with the rest rather than being filtered out. A page
    the census has marked gone keeps the date of the last edit it ever had,
    which is true, and is what a reader asking why a script disappeared wants;
    excluding them would freeze that row at whatever the last sweep happened to
    see and leave it reading as though the page were still current.
    """
    return tuple(
        session.query(UserScriptPage)
        .filter(UserScriptPage.wiki == wiki, UserScriptPage.id > after)
        .order_by(UserScriptPage.id)
        .limit(BATCH)
        .all()
    )


def record_gadgets(wiki: str, dates: dict[str, str]) -> int:
    """Write last-edit dates onto one wiki's gadgets. Returns how many moved.

    Paged by id rather than by re-asking which rows are out of date. Every row
    is offered on every pass -- a last edit is not written once, it is the field
    that keeps moving -- so there is no shrinking "what is missing" set here and
    none of the risk of the loop that never ends when such a set has a floor.
    """
    if not dates:
        return 0
    written = 0
    after = 0
    while True:
        with db.session_scope() as session:
            rows = _pending_gadgets(session, wiki, after)
            if not rows:
                return written
            after = rows[-1].id
            written += _stamp_gadgets(rows, dates)


def record_scripts(wiki: str, dates: dict[str, str]) -> int:
    """Write last-edit dates onto one wiki's script pages. Returns how many moved.

    Paged by id on the same terms as `record_gadgets`, over a corpus three
    orders of magnitude larger: enwiki alone holds tens of thousands of these.
    """
    if not dates:
        return 0
    written = 0
    after = 0
    while True:
        with db.session_scope() as session:
            rows = _pending_scripts(session, wiki, after)
            if not rows:
                return written
            after = rows[-1].id
            written += _stamp_scripts(rows, dates)


def backfill_gadgets(
    wikis: Sequence[str],
    *,
    connect: wiki_replica.Connect = wiki_replica.open_connection,
    known: Mapping[str, wiki_replica.Address] | None = None,
) -> dict[str, int]:
    """Date each wiki's gadgets, and report how many rows moved.

    Wikis whose replica did not answer are omitted rather than reported as zero,
    so a caller can tell "nothing had been edited" from "there was no replica".
    The two look identical in a count and want different reactions from whoever
    reads the log.
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
            dates = wiki_replica.gadget_edit_dates_for(
                address.dbname, section=address.section, user=user, connect=connect
            )
        except Exception:  # noqa: BLE001, S112 - one wiki's outage must not hide the others
            continue
        written[wiki] = record_gadgets(wiki, dates)
    return written


def backfill_scripts(
    wikis: Sequence[str],
    *,
    connect: wiki_replica.Connect = wiki_replica.open_connection,
    known: Mapping[str, wiki_replica.Address] | None = None,
) -> dict[str, int]:
    """Date each wiki's user-space script pages, on the same terms as the gadgets."""
    user, addresses = wiki_replica.resolve(wikis, connect=connect, known=known)
    if user is None:
        return {}
    written: dict[str, int] = {}
    for wiki in wikis:
        address = addresses.get(wiki)
        if address is None:
            continue
        try:
            dates = wiki_replica.script_edit_dates_for(
                address.dbname, section=address.section, user=user, connect=connect
            )
        except Exception:  # noqa: BLE001, S112 - one wiki's outage must not hide the others
            continue
        written[wiki] = record_scripts(wiki, dates)
    return written
