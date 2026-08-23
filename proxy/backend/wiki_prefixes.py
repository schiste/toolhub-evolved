# SPDX-License-Identifier: GPL-3.0-or-later
"""What a title's leading `X:` means on each wiki, stored so titles fold everywhere.

`backend.userscripts` folds a localized user namespace onto `User:` so that one
page has one title, and follows an interwiki prefix to the wiki it names so that
one page has one wiki. Until this module existed it could fold exactly three
spellings -- `User`, `Utilisateur`, `Utilisatrice` -- and could follow no
prefixes at all, so `Benutzer:X/common.js` was stored as a title no page will
ever answer to and `en:User:Lupin/popups.js` was stored as a title on the wrong
wiki. Both resolve to nothing.

The names come from `meta=siteinfo`, which is one request per wiki and returns
the namespace names, their aliases, and the interwiki map at once. They are
stored because the two passes that need them run in different processes -- the
census reads wikis, the projection reads only the database -- and because a
namespace name changes about as often as a wiki is renamed.

Read failures are not destructive here. A wiki that could not be reached keeps
whatever prefixes it already had, and a wiki that has never been read falls back
to the built-ins, which is exactly the behavior that existed before. This module
can widen what resolves and cannot narrow it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import db, userscripts, wiki_api
from backend.models import WikiTitlePrefixes, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

REFRESH_AFTER_DAYS = 30

RETRY_AFTER_HOURS = 6

STATUS_READ = "read"
STATUS_UNREADABLE = "unreadable"

MAX_SPELLINGS = 32


def siteinfo_params() -> dict[str, Any]:
    """Parameters asking a wiki for its namespace names, aliases, and interwiki map."""
    return {"action": "query", **wiki_api.SITEINFO_PARAMS}


def _stored(session: Session, wiki: str) -> WikiTitlePrefixes | None:
    return session.execute(select(WikiTitlePrefixes).where(WikiTitlePrefixes.wiki == wiki)).scalar_one_or_none()


def _clean_namespaces(spellings: object) -> tuple[str, ...]:
    """Return stored namespace spellings as the tuple the fold wants, dropping junk.

    Read defensively because the column is JSON written by an earlier version of
    this code as much as by this one, and because a spelling that is not a
    string would reach `re.escape` and raise inside a census that has nothing to
    do with namespaces.
    """
    if not isinstance(spellings, list):
        return ()
    return tuple(str(item).strip() for item in spellings[:MAX_SPELLINGS] if str(item or "").strip())


def _clean_interwiki(hosts: object) -> dict[str, str]:
    """Return the stored interwiki map as prefix -> host, dropping junk.

    Defensive for the same reason as the namespaces, with one addition: the
    prefix is casefolded on the way out as well as on the way in, because it is
    looked up by a casefolded prefix read off a page title and a row written
    before that was true would otherwise never match.
    """
    if not isinstance(hosts, dict):
        return {}
    found: dict[str, str] = {}
    for prefix, host in list(hosts.items())[: wiki_api.MAX_INTERWIKI_PREFIXES]:
        key = str(prefix or "").strip().casefold()
        target = str(host or "").strip().lower()
        if key and target:
            found[key] = target
    return found


def _prefixes(row: WikiTitlePrefixes | None) -> userscripts.WikiPrefixes:
    """Return what one stored row means to the fold, or nothing for no row."""
    if row is None:
        return userscripts.WikiPrefixes()
    return userscripts.WikiPrefixes(
        namespaces=_clean_namespaces(row.namespaces),
        interwiki=_clean_interwiki(row.interwiki),
    )


def stored_prefixes(session: Session, wiki: str) -> userscripts.WikiPrefixes:
    """Return the prefixes held for one wiki, or none if it has never been read."""
    return _prefixes(_stored(session, wiki))


def is_stale(row: WikiTitlePrefixes | None) -> bool:
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
    """Read one wiki's namespace names and interwiki map and store them.

    Returns what happened rather than the prefixes, so a job can report a wiki
    it could not read. The prefixes themselves are read back through `resolver`,
    which is the only thing that should be handing them to the fold.

    A payload with no namespace 2 in it is treated as unread even when it
    carries an interwiki map, because that is the shape of an error page rather
    than of a wiki: every MediaWiki install has a user namespace.
    """
    try:
        payload = request(wiki, "GET", siteinfo_params())
    except Exception:  # noqa: BLE001 - one wiki failing is not the job failing
        return _unread(wiki, STATUS_UNREADABLE)
    spellings = wiki_api.user_namespace_spellings(payload)
    if not spellings:
        return _unread(wiki, STATUS_UNREADABLE)
    interwiki = wiki_api.interwiki_hosts(payload)
    with db.session_scope() as session:
        row = _stored(session, wiki)
        if row is None:
            row = WikiTitlePrefixes(wiki=wiki)
            session.add(row)
        row.namespaces = list(spellings[:MAX_SPELLINGS])
        row.interwiki = interwiki
        row.read_at = row.checked_at = utcnow()
        row.status = STATUS_READ
    return {"wiki": wiki, "status": STATUS_READ, "spellings": len(spellings), "interwiki": len(interwiki)}


def _unread(wiki: str, status: str) -> dict[str, Any]:
    """Record that a read was attempted, without discarding what was already known."""
    with db.session_scope() as session:
        row = _stored(session, wiki)
        if row is None:
            row = WikiTitlePrefixes(wiki=wiki, namespaces=[], interwiki={})
            session.add(row)
        # `read_at` is deliberately untouched: it dates the prefixes, and these
        # are still the ones from whenever they were last actually read. Only
        # the attempt is recorded, and that is what holds off the next one.
        row.checked_at = utcnow()
        row.status = status
    return {"wiki": wiki, "status": status, "spellings": 0, "interwiki": 0}


def resolver(
    session: Session,
    request: Callable[[str, str, dict[str, Any]], Any] | None = None,
) -> userscripts.Prefixes:
    """Return a lookup from wiki to the prefixes its titles can carry.

    Memoized per call because one sweep asks about the same handful of wikis
    tens of thousands of times -- every load edge on every page resolves its
    target's namespace -- and a query each is worth avoiding even though it is
    the two clocks on the row, not this dict, that keep the *requests* to one.

    With no `request` this reads only what is stored, which is what the
    projection wants: it has no business making requests, and a wiki nobody has
    read yet simply folds on the built-ins.
    """
    known: dict[str, userscripts.WikiPrefixes] = {}

    def prefixes_for(wiki: str) -> userscripts.WikiPrefixes:
        if not wiki:
            return userscripts.WikiPrefixes()
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
        known[wiki] = _prefixes(row)
        return known[wiki]

    return prefixes_for
