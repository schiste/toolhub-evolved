# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeping a local copy of which Wikimedia wikis exist, and where each one lives.

The censuses used to cover a list of wikis written into a job's environment.
That works for three and stops working at a thousand: nobody maintains a
thousand-entry environment variable, and it would be wrong the first time a wiki
is created. `meta_p.wiki` already answers the question -- it lists every wiki
with a public replica, which is exactly the set that can be read -- so the
roster is taken from there and kept here.

Kept rather than asked per run because the answer changes a few times a year
while the lanes that need it run every hour. It also carries the replica
section, which is what lets a pass over hundreds of wikis open one connection
per instance instead of one per wiki.

Best effort on the same terms as the rest of the replica lanes: a host with no
`replica.my.cnf`, or a replica that will not answer, leaves the table exactly as
it was and raises nothing. A registry that is a week stale still names a
thousand wikis correctly; one that raised would take the census down with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend import db, wiki_replica
from backend.models import WikiProject, utcnow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

# Rows per transaction. The roster is about a thousand rows and the write is a
# handful of short columns each, so this is not about memory -- it bounds how
# long one transaction holds a table the census reads on every tick.
BATCH: int = 250


def _apply(row: WikiProject, entry: wiki_replica.WikiRow, seen_at: object) -> bool:
    """Copy one roster entry onto its stored row. Returns whether anything moved.

    `last_seen_at` moves on every pass because it is what dates the roster, but
    the identity columns are written only when they differ. A thousand-row job
    that rewrote every row weekly would be harmless; one that also woke up the
    replication of every row for no change is the pattern this codebase has been
    bitten by before, and the guard costs one comparison.
    """
    changed = False
    for field, value in (
        ("dbname", entry.dbname),
        ("section", entry.section),
        ("family", entry.family),
        ("lang", entry.lang),
        ("closed", entry.closed),
    ):
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    # A wiki that came back is not retired any more, whatever it was before.
    if row.retired_at is not None:
        row.retired_at = None
        changed = True
    row.last_seen_at = seen_at
    return changed


def _store(session: Session, entries: Sequence[wiki_replica.WikiRow], seen_at: object) -> tuple[int, int]:
    """Upsert one batch of roster entries. Returns (added, updated)."""
    existing = {
        row.wiki: row
        for row in session.query(WikiProject).filter(WikiProject.wiki.in_([entry.wiki for entry in entries])).all()
    }
    added = updated = 0
    for entry in entries:
        row = existing.get(entry.wiki)
        if row is None:
            row = WikiProject(wiki=entry.wiki, first_seen_at=seen_at)
            session.add(row)
            _apply(row, entry, seen_at)
            added += 1
            continue
        if _apply(row, entry, seen_at):
            updated += 1
    return added, updated


def _retire(session: Session, present: set[str], seen_at: object) -> int:
    """Mark the wikis this pass did not see. Returns how many were newly retired.

    Marked, never deleted: their pages are still in the census and their
    catalogue records still exist, and a wiki missing from one roster read is
    not a wiki whose scripts stopped existing. Only rows that were live before
    are touched, so a wiki that has been gone for months is not rewritten every
    week to say so again.
    """
    stale = session.query(WikiProject).filter(WikiProject.retired_at.is_(None), WikiProject.wiki.notin_(present)).all()
    for row in stale:
        row.retired_at = seen_at
    return len(stale)


def refresh(*, connect: wiki_replica.Connect = wiki_replica.open_connection) -> dict:
    """Read the roster from `meta_p` and bring the local table into line.

    Reports `read=0` when there was no replica to ask, which a caller reads as
    "the registry is as good as it was" rather than as "there are no wikis".
    Nothing is retired in that case: an empty answer is not evidence that every
    wiki in the world closed at once, and treating it as one would retire the
    whole registry on a single unreachable replica.
    """
    summary = {"read": 0, "added": 0, "updated": 0, "retired": 0, "reason": ""}
    user = wiki_replica.credentials()
    if user is None:
        summary["reason"] = "no-credentials"
        return summary
    try:
        entries = wiki_replica.roster_for(user=user, connect=connect)
    except Exception as error:  # noqa: BLE001 - an unreachable replica is not a failed job
        summary["reason"] = f"unreadable:{type(error).__name__}"
        return summary
    if not entries:
        summary["reason"] = "empty"
        return summary
    seen_at = utcnow()
    summary["read"] = len(entries)
    for start in range(0, len(entries), BATCH):
        with db.session_scope() as session:
            added, updated = _store(session, entries[start : start + BATCH], seen_at)
        summary["added"] += added
        summary["updated"] += updated
    with db.session_scope() as session:
        summary["retired"] = _retire(session, {entry.wiki for entry in entries}, seen_at)
    return summary


def projects(*, include_closed: bool = True, include_retired: bool = False) -> tuple[WikiProject, ...]:
    """Read the registry, ordered by section so a caller can group by connection.

    Closed wikis are included by default because their scripts are real and have
    to be discovered once; it is the schedule's business, not the registry's, to
    visit them rarely. Retired ones are excluded by default because they are no
    longer readable at all.
    """
    with db.session_scope() as session:
        query = session.query(WikiProject)
        if not include_retired:
            query = query.filter(WikiProject.retired_at.is_(None))
        if not include_closed:
            query = query.filter(WikiProject.closed.is_(False))
        rows = query.order_by(WikiProject.section, WikiProject.wiki).all()
        for row in rows:
            session.expunge(row)
        return tuple(rows)
