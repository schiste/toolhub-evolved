# SPDX-License-Identifier: GPL-3.0-or-later
"""Naming every user-space script page on a wiki, by the best road available.

Discovery has two roads and they are not equivalent. The search index answers
`contentmodel:javascript` for any wiki from anywhere, and refuses an offset of
10,000 or more -- so on Meta, which holds 25,354 JavaScript pages, it can name
the first ten thousand and nothing else. That is not a paging inconvenience to
work around: `prefix:` clauses do not compose in CirrusSearch (two of them are
silently dropped, and two positive ones return nothing), so the index cannot be
partitioned into walkable pieces and cannot be made to prove it named everything.

The Wiki Replicas answer the same question exactly, as one indexed read:

    SELECT page_content_model, page_title
    FROM page WHERE page_namespace = 2 AND page_content_model IN ('javascript', 'css')
    ORDER BY page_id

No cap, no paging, and consistently *more* complete than the index -- measured
on 2026-08-22, metawiki has 34,814 such pages against the index's 23,596, and
enwiki 155,561 against 98,790. Namespace-2 pages always record an explicit
content model, so the predicate is exact rather than a suffix guess: it catches
the pages holding JavaScript under a name that does not end in `.js`, and skips
the wikitext pages that do.

So the replica is preferred and the search is the fallback, not the other way
round. The fallback is not vestigial: replicas are reachable only from inside
Toolforge, and a laptop, CI, or any host without `replica.my.cnf` still has to
be able to run a census. What the fallback gives up is completeness on a large
wiki, and it says so -- `complete` stays false and the sweep declines to
tombstone anything on the strength of a list it knows is a prefix of the truth.

Which road a census took is therefore part of what it is, not a detail of how
it was built, and `superseded` is how a stored census is asked whether the road
behind it still is the best one. It has to be asked, because a finished sweep
never runs again on its own: frwiki was swept from the index the day before the
replica road landed, and kept a census 920 pages short of its user space for as
long as nobody noticed.

`page_id` order is creation order for free. Ids are handed out in creation
sequence and never reused, so the position of a title in this list is the
ordering `backend.userscript_projection` reads as creation order wherever the
replica has not supplied a real timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend import userscript_census as census
from backend import wiki_replica

if TYPE_CHECKING:
    from collections.abc import Callable

#: Where an enumeration came from, reported so a run that fell back is legible.
SOURCE_REPLICA = "replica"
SOURCE_SEARCH = "search"
SOURCE_SEARCH_FALLBACK = "search-fallback"


@dataclass(frozen=True)
class Enumeration:
    """Every script page one road could name on a wiki, in creation order.

    `complete` is the honest part, and the sweep leans on it twice: a partial
    list may not tombstone the pages it never mentioned, and a cursor into it
    means nothing, because the next run's list may not begin where this one did.
    """

    titles: tuple[str, ...]
    totals: dict[str, int]
    complete: bool
    source: str


def _by_search(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    *,
    source: str = SOURCE_SEARCH,
) -> Enumeration:
    """Walk the search index for each script model, keeping its own honesty.

    `source` separates the two ways a census ends up here, which look identical
    in the result and are opposite in what to do about them. `SOURCE_SEARCH` is
    a host that never had the better road and may acquire it; falling back with
    credentials in hand means the replica was tried and did not answer, and
    trying again on the next run would fall back again.
    """

    def search(query: str, offset: int) -> tuple[int, tuple[str, ...]]:
        return census.read_search(request(wiki, "GET", census.search_params(query, offset)))

    titles: list[str] = []
    totals: dict[str, int] = {}
    complete = True
    for model in (census.SCRIPT_MODEL, census.STYLE_MODEL):
        found = census.enumerate_titles(search, model)
        titles.extend(found.titles)
        totals[model] = found.total
        complete = complete and found.complete
    return Enumeration(titles=tuple(titles), totals=totals, complete=complete, source=source)


def _prefix(request: Callable[[str, str, dict[str, Any]], Any], wiki: str) -> str:
    """Ask a wiki what it calls namespace 2, which is what its titles are stored as.

    One request, and the whole replica road depends on it. The replica stores
    `page_title` without a namespace, so the prefix has to come from somewhere;
    it has to be the wiki's own name for it -- frwiki says `Utilisateur` -- and
    not the canonical `User`, because the census keys ranks, stored revisions
    and tombstones on the title, and asking under the canonical spelling would
    get every answer back spelled the other way.
    """
    return census.read_namespace_prefix(request(wiki, "GET", census.siteinfo_params()))


def _by_replica(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    *,
    user: wiki_replica.Credentials,
    connect: wiki_replica.Connect,
) -> Enumeration | None:
    """Read the wiki's whole script corpus from its replica, or None if it cannot.

    None rather than an exception, and None rather than an empty enumeration:
    every way this can fail -- no row in `meta_p` for the wiki, an unreachable
    replica, a wiki that does not name namespace 2 -- means "ask the other road",
    and an empty enumeration reported as complete would tombstone the wiki.
    """
    dbname = wiki_replica.dbnames_for([wiki], user=user, connect=connect).get(wiki)
    if not dbname:
        return None
    prefix = _prefix(request, wiki)
    if not prefix:
        return None
    rows = wiki_replica.script_titles_for(dbname, user=user, connect=connect)
    if not rows:
        return None
    totals: dict[str, int] = {census.SCRIPT_MODEL: 0, census.STYLE_MODEL: 0}
    titles: list[str] = []
    for model, page_title in rows:
        totals[model] = totals.get(model, 0) + 1
        titles.append(census.full_title(prefix, page_title))
    return Enumeration(titles=tuple(titles), totals=totals, complete=True, source=SOURCE_REPLICA)


def enumerate_wiki(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    *,
    credentials: Callable[[], wiki_replica.Credentials | None] = wiki_replica.credentials,
    connect: wiki_replica.Connect = wiki_replica.open_connection,
) -> Enumeration:
    """Name every script page on a wiki, preferring the exact road over the capped one.

    A replica failure is not a census failure. Falling back costs completeness
    on a large wiki and nothing at all on a small one, and the result says which
    road it took so a run that quietly stopped being exact is visible in the log
    rather than only in a count that stopped growing.
    """
    user = credentials()
    if user is None:
        return _by_search(request, wiki)
    try:
        found = _by_replica(request, wiki, user=user, connect=connect)
    except Exception:  # noqa: BLE001 - an unreachable replica falls back, it does not fail the census
        found = None
    if found is not None:
        return found
    return _by_search(request, wiki, source=SOURCE_SEARCH_FALLBACK)


def superseded(
    source: str,
    *,
    credentials: Callable[[], wiki_replica.Credentials | None] = wiki_replica.credentials,
) -> bool:
    """Whether an enumeration recorded as `source` could be bettered on this host now.

    Only the plain search road can be. It is what a host without replica
    credentials gets, and a host that has since acquired them can name pages
    that road structurally cannot reach -- so a census built on it is worth
    building again. `SOURCE_SEARCH_FALLBACK` is the same list obtained *despite*
    having the credentials, which is a replica that did not answer rather than
    one that is not there; calling it superseded would sweep the wiki on every
    run for as long as the failure lasts. An empty source is a census recorded
    before the road was written down: unknown rather than exact, so it is
    checked once and then knows what it is.
    """
    return source in ("", SOURCE_SEARCH) and credentials() is not None
