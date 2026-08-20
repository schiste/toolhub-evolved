# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding a wiki's user scripts, and reading them, through the public API.

Discovery asks the search index for pages whose *content model* is javascript or
css, which is the same boundary `backend.userscripts` draws and for the same
reason: `User:Penquista/monobook.css` holds JavaScript, and any enumeration that
trusts the file suffix both misses it and miscategorises it. MediaWiki records
the model per page, CirrusSearch indexes it, and asking for it directly is the
only route that agrees with what the parser actually does.

The alternative -- walking `list=allpages` over the user namespace and filtering
on the suffix -- is exhaustive but reads several hundred thousand titles to find
nine thousand pages, and gets the suffix question wrong at the end of it.

Nothing here fetches on its own. The Action API calls go through the existing
`WikimediaClient`, which validates the host before every request; this module
supplies the queries, the paging, and the reading of the answers.

Two limits shape the code rather than the other way round. Search refuses an
offset of 10,000 or more, so a model with more hits than that cannot be walked
in one query and the count is reported instead of quietly truncated -- an
enumeration that silently stops at 10,000 looks exactly like a complete one.
And the API caps a response at 2 MB, which a batch of large scripts can exceed,
so a batch that comes back too large is split rather than dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

# Content models worth a directory entry. CSS is enumerated because a page's
# model is not its suffix: a .css page holding JavaScript is a script, and a
# .js page holding CSS is not one. Which of them is a *candidate* is decided
# later, by role, not here.
SCRIPT_MODEL: Final = "javascript"
STYLE_MODEL: Final = "css"

USER_NAMESPACE: Final = 2

# CirrusSearch rejects sroffset >= 10000 outright (cirrussearch-offset-too-large).
SEARCH_OFFSET_CAP: Final = 10_000
SEARCH_PAGE_SIZE: Final = 500

# Titles per content request. Small because the API caps a response at 2 MB and
# a single user script can run to six figures of bytes; a batch that still comes
# back too large is halved rather than abandoned.
CONTENT_BATCH: Final = 20


@dataclass(frozen=True)
class Discovery:
    """Every page of one content model that the search index will name.

    `complete` is the honest part. False means the wiki holds more pages of this
    model than one search can walk, so `titles` is a prefix of the truth and the
    caller must narrow the query -- by title prefix -- rather than treat the
    result as the wiki's full set.
    """

    model: str
    titles: tuple[str, ...]
    total: int
    complete: bool


@dataclass(frozen=True)
class PageContent:
    """One page as the API returned it, before any analysis."""

    title: str
    model: str
    body: str
    revision: str
    touched: str


def search_query(model: str, *, prefix: str = "") -> str:
    """Build the search that names every page of one content model.

    `prefix` narrows to titles starting with it, which is how a wiki too large
    for a single walk gets broken into walkable pieces.
    """
    query = f"contentmodel:{model}"
    return f"{query} prefix:{prefix}" if prefix else query


def enumerate_titles(
    search: Callable[[str, int], tuple[int, Sequence[str]]],
    model: str,
    *,
    prefix: str = "",
) -> Discovery:
    """Walk the search index for one content model, or report that it cannot be.

    `search(query, offset)` returns the total hit count and one page of titles.
    Injecting it keeps the paging -- the part with the off-by-one risks and the
    cap -- testable without a network.
    """
    query = search_query(model, prefix=prefix)
    total, first = search(query, 0)
    if total >= SEARCH_OFFSET_CAP:
        return Discovery(model=model, titles=tuple(first), total=total, complete=False)
    titles: list[str] = list(first)
    while len(titles) < total and first:
        _total, first = search(query, len(titles))
        titles.extend(first)
    return Discovery(model=model, titles=tuple(titles), total=total, complete=True)


def is_script_page(title: str, namespace: int) -> bool:
    """Whether a recent-changes entry is worth fetching at all.

    Recent changes cannot be filtered by content model, so this is the one place
    the suffix is used -- not to decide what a page *is*, but to avoid fetching
    every new user page on the wiki to find out. The model is read from the page
    itself once it arrives.
    """
    return namespace == USER_NAMESPACE and title.casefold().endswith((".js", ".css"))


def _page_content(page: object) -> PageContent | None:
    """Read one page out of an Action API query result, or None if it has none."""
    if not isinstance(page, dict) or page.get("missing") or page.get("invalid"):
        return None
    revisions = page.get("revisions")
    revision = revisions[0] if isinstance(revisions, list) and revisions else None
    if not isinstance(revision, dict):
        return None
    slots = revision.get("slots")
    main = slots.get("main") if isinstance(slots, dict) else None
    if not isinstance(main, dict):
        return None
    return PageContent(
        title=str(page.get("title") or ""),
        model=str(main.get("contentmodel") or ""),
        body=str(main.get("content") or ""),
        revision=str(revision.get("revid") or ""),
        touched=str(revision.get("timestamp") or ""),
    )


def read_pages(payload: object) -> tuple[PageContent, ...]:
    """Pull every readable page out of one `action=query&prop=revisions` answer.

    Pages the API reports as missing, invalid, or empty of slots are skipped
    rather than raised on: a page deleted between discovery and fetch is an
    ordinary event in a census that runs for minutes over a live wiki.
    """
    query = payload.get("query") if isinstance(payload, dict) else None
    pages = query.get("pages") if isinstance(query, dict) else None
    if not isinstance(pages, list):
        return ()
    return tuple(content for page in pages if (content := _page_content(page)) is not None)


def content_params(titles: Iterable[str]) -> dict[str, Any]:
    """Parameters asking for the current source of up to CONTENT_BATCH pages."""
    return {
        "action": "query",
        "prop": "revisions",
        "rvprop": "ids|timestamp|content",
        "rvslots": "main",
        "titles": "|".join(titles),
    }


def batched(titles: Sequence[str], size: int = CONTENT_BATCH) -> Iterator[tuple[str, ...]]:
    """Split titles into request-sized groups, skipping nothing."""
    for start in range(0, len(titles), size):
        yield tuple(titles[start : start + size])


def search_params(query: str, offset: int) -> dict[str, Any]:
    """Parameters for one page of a content-model search over user space."""
    params: dict[str, Any] = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": USER_NAMESPACE,
        "srlimit": SEARCH_PAGE_SIZE,
        "srprop": "",
    }
    if offset:
        params["sroffset"] = offset
    return params


def read_search(payload: object) -> tuple[int, tuple[str, ...]]:
    """Read the hit count and titles out of one search answer."""
    query = payload.get("query") if isinstance(payload, dict) else None
    if not isinstance(query, dict):
        return (0, ())
    info = query.get("searchinfo")
    total = int(info.get("totalhits") or 0) if isinstance(info, dict) else 0
    results = query.get("search")
    if not isinstance(results, list):
        return (total, ())
    return (total, tuple(str(item.get("title") or "") for item in results if isinstance(item, dict)))


def changes_params(since: str, limit: int) -> dict[str, Any]:
    """Parameters listing user-space pages changed since a timestamp.

    Both new pages and edits are asked for. A script that already existed and
    was rewritten this morning is as much a change to the directory as one
    created this morning, and `rctype=new` alone would miss every one of them.
    """
    params: dict[str, Any] = {
        "action": "query",
        "list": "recentchanges",
        "rcnamespace": USER_NAMESPACE,
        "rctype": "new|edit",
        "rcprop": "title|timestamp",
        "rclimit": limit,
        "rcdir": "newer",
    }
    if since:
        params["rcstart"] = since
    return params


def read_changes(payload: object) -> tuple[str, ...]:
    """Titles of changed user-space script pages, in the order reported, once each."""
    query = payload.get("query") if isinstance(payload, dict) else None
    changes = query.get("recentchanges") if isinstance(query, dict) else None
    if not isinstance(changes, list):
        return ()
    seen: set[str] = set()
    found: list[str] = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        title = str(change.get("title") or "")
        if not is_script_page(title, int(change.get("ns") or 0)) or title in seen:
            continue
        seen.add(title)
        found.append(title)
    return tuple(found)
