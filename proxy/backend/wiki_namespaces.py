# SPDX-License-Identifier: GPL-3.0-or-later
"""What each wiki calls its user namespace, stored so titles fold everywhere.

`backend.userscripts` folds a localized user namespace onto `User:` so that one
page has one title. Until this module existed it could fold exactly three
spellings -- `User`, `Utilisateur`, `Utilisatrice` -- which are the names the
two wikis censused first happen to use. Every other wiki's name went unfolded,
so `Benutzer:X/common.js` was stored as a title no page will ever answer to and
its load edge resolved to nothing.

The names come from `meta=siteinfo`, which is one request per wiki and returns
the canonical name, the localized name, and every alias at once. They are
stored because the two passes that need them run in different processes -- the
census reads wikis, the projection reads only the database -- and because a
namespace name changes about as often as a wiki is renamed.

Read failures are not destructive here. A wiki that could not be reached keeps
whatever spellings it already had, and a wiki that has never been read falls
back to the built-ins, which is exactly the behavior that existed before. This
module can widen the fold and cannot narrow it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import db, wiki_api
from backend.models import WikiNamespaceSpelling, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

# How long a stored reading is used before it is read again. Namespace names
# outlive most things in this database; this is short enough that a rename is
# picked up within a month and long enough that no run spends requests on it.
REFRESH_AFTER_DAYS = 30

# How long a failed read is left alone before being tried again. Much shorter
# than the refresh interval because a wiki that could not be reached is usually
# a wiki that was busy, not one that has stopped existing -- but long enough
# that a permanently unreachable wiki costs a few requests a day rather than a
# few on every pass over the corpus.
RETRY_AFTER_HOURS = 6

STATUS_READ = "read"
STATUS_UNREADABLE = "unreadable"

# A wiki declaring more names than this for one namespace is not a wiki this
# code should be building a regular expression out of.
MAX_SPELLINGS = 32


def siteinfo_params() -> dict[str, Any]:
    """Parameters asking a wiki for its namespace names and aliases."""
    return {"action": "query", **wiki_api.SITEINFO_PARAMS}


def _stored(session: Session, wiki: str) -> WikiNamespaceSpelling | None:
    return session.execute(select(WikiNamespaceSpelling).where(WikiNamespaceSpelling.wiki == wiki)).scalar_one_or_none()


def _clean(spellings: object) -> tuple[str, ...]:
    """Return stored spellings as the tuple the fold wants, dropping junk.

    Read defensively because the column is JSON written by an earlier version of
    this code as much as by this one, and because a spelling that is not a
    string would reach `re.escape` and raise inside a census that has nothing to
    do with namespaces.
    """
    if not isinstance(spellings, list):
        return ()
    return tuple(str(item).strip() for item in spellings[:MAX_SPELLINGS] if str(item or "").strip())


def stored_spellings(session: Session, wiki: str) -> tuple[str, ...]:
    """Return the spellings held for one wiki, or none if it has never been read."""
    row = _stored(session, wiki)
    return _clean(row.spellings) if row else ()


def is_stale(row: WikiNamespaceSpelling | None) -> bool:
    """Report whether this wiki should be read again before being relied on.

    Two clocks, because a wiki that answered and a wiki that refused are not
    due back at the same time. A successful reading is trusted for a month; a
    failed attempt is retried within hours, but not within the same run.
    """
    if row is None:
        return True
    if row.read_at is not None:
        return (utcnow() - row.read_at).days >= REFRESH_AFTER_DAYS
    if row.checked_at is None:
        return True
    return (utcnow() - row.checked_at).total_seconds() >= RETRY_AFTER_HOURS * 3600


def refresh(request: Callable[[str, str, dict[str, Any]], Any], wiki: str) -> dict[str, Any]:
    """Read one wiki's user-namespace names and store them.

    Returns what happened rather than the names, so a job can report a wiki it
    could not read. The names themselves are read back through `resolver`,
    which is the only thing that should be handing them to the fold.
    """
    try:
        payload = request(wiki, "GET", siteinfo_params())
    except Exception:  # noqa: BLE001 - one wiki failing is not the job failing
        return _unread(wiki, STATUS_UNREADABLE)
    spellings = wiki_api.user_namespace_spellings(payload)
    if not spellings:
        # A payload with no namespace 2 is an answer this code cannot use, and
        # is recorded as unreadable rather than as "this wiki has no names".
        return _unread(wiki, STATUS_UNREADABLE)
    with db.session_scope() as session:
        row = _stored(session, wiki)
        if row is None:
            row = WikiNamespaceSpelling(wiki=wiki)
            session.add(row)
        row.spellings = list(spellings[:MAX_SPELLINGS])
        row.read_at = row.checked_at = utcnow()
        row.status = STATUS_READ
    return {"wiki": wiki, "status": STATUS_READ, "spellings": len(spellings)}


def _unread(wiki: str, status: str) -> dict[str, Any]:
    """Record that a read was attempted, without discarding what was already known."""
    with db.session_scope() as session:
        row = _stored(session, wiki)
        if row is None:
            row = WikiNamespaceSpelling(wiki=wiki, spellings=[])
            session.add(row)
        # `read_at` is deliberately untouched: it dates the spellings, and these
        # are still the ones from whenever they were last actually read. Only
        # the attempt is recorded, and that is what holds off the next one.
        row.checked_at = utcnow()
        row.status = status
    return {"wiki": wiki, "status": status, "spellings": 0}


def resolver(
    session: Session,
    request: Callable[[str, str, dict[str, Any]], Any] | None = None,
) -> Callable[[str], tuple[str, ...]]:
    """Return a lookup from wiki to its user-namespace spellings.

    Memoized per call because one sweep asks about the same handful of wikis
    tens of thousands of times -- every load edge on every page resolves its
    target's namespace -- and a query each is worth avoiding even though it is
    the two clocks on the row, not this dict, that keep the *requests* to one.

    With no `request` this reads only what is stored, which is what the
    projection wants: it has no business making requests, and a wiki nobody has
    read yet simply folds on the built-ins.
    """
    known: dict[str, tuple[str, ...]] = {}

    def spellings_for(wiki: str) -> tuple[str, ...]:
        if not wiki:
            return ()
        if wiki in known:
            return known[wiki]
        row = _stored(session, wiki)
        if request is not None and is_stale(row):
            refresh(request, wiki)
            # Re-read through a fresh statement rather than trusting the write:
            # `refresh` commits in its own session, so this one's identity map
            # is holding the row as it was before.
            session.expire_all()
            row = _stored(session, wiki)
        known[wiki] = _clean(row.spellings) if row else ()
        return known[wiki]

    return spellings_for
