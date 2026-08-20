# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading one wiki's user scripts into the directory, and keeping them current.

Two passes over the same machinery. A *sweep* walks the search index for every
page of a script content model, and is how a wiki first enters the directory. A
*watch* follows recent changes since the last run, and is how it stays current.
Between them they are the difference between a census and a directory.

Neither is transactional across the wiki, and neither pretends to be. A census
that runs for minutes over a live wiki will see pages created, edited and
deleted underneath it, and the honest response to each is a row rather than an
exception. Per `backend.job_contract`, a page that cannot be read is a durable
observation; only a sweep that could not run at all is a job failure.

Work is skipped by revision id. Re-reading a wiki costs thousands of requests
while re-analysing a stored page costs microseconds, so a page whose revision
has not moved is left untouched -- which is what makes a frequent watch cheap
enough to be worth scheduling at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func

from backend import db, userscripts
from backend import userscript_census as census
from backend.models import UserScriptCensusState, UserScriptImport, UserScriptPage, utcnow
from backend.userscript_directory import basename_of, owner_of_user_page

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from sqlalchemy.orm import Session

# Bodies are stored so re-analysis stays free, but no single page may dominate
# the table. MEDIUMTEXT holds far more than this; the cap is about what is worth
# keeping, not about what fits.
MAX_STORED_BODY: int = 512 * 1024
MAX_STORED_URL: int = 2000
# One recent-changes window. Large enough that an hourly watch on a busy wiki
# never truncates, small enough to stay one request.
WATCH_LIMIT: int = 500

# How many failed batches are worth re-reading one title at a time before the
# failure is treated as systemic rather than as one oversized batch.
SPLIT_BUDGET: int = 5

EMPTY_COUNTS: dict[str, int] = {"asked": 0, "fetched": 0, "written": 0, "skipped": 0, "unreadable": 0}


def _searcher(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
) -> Callable[[str, int], tuple[int, tuple[str, ...]]]:
    """Bind a wiki to the search callable `census.enumerate_titles` expects."""

    def search(query: str, offset: int) -> tuple[int, tuple[str, ...]]:
        return census.read_search(request(wiki, "GET", census.search_params(query, offset)))

    return search


def discover(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
) -> tuple[tuple[str, ...], dict[str, int], bool]:
    """Every script-model title on a wiki, in creation order, with per-model totals.

    Order matters and is not incidental: enumeration sorts by creation, so the
    position of a title in this sequence is the only creation ordering the
    directory needs, obtained without a single extra request.
    """
    titles: list[str] = []
    totals: dict[str, int] = {}
    complete = True
    for model in (census.SCRIPT_MODEL, census.STYLE_MODEL):
        found = census.enumerate_titles(_searcher(request, wiki), model)
        titles.extend(found.titles)
        totals[model] = found.total
        complete = complete and found.complete
    return (tuple(titles), totals, complete)


def _read_batch(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    batch: Sequence[str],
) -> tuple[tuple[census.PageContent, ...], bool]:
    """Read one batch of titles, reporting failure rather than raising it."""
    try:
        payload = request(wiki, "GET", census.content_params(batch))
    except Exception:  # noqa: BLE001 - a failed read is one gap in the census, never a job failure
        return ((), False)
    return (census.read_pages(payload), True)


def read_titles(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    titles: Sequence[str],
) -> tuple[list[census.PageContent], int]:
    """Fetch and parse pages in API-sized batches, counting the titles left unread.

    A batch can fail for the batch's own sake: twenty user scripts can exceed the
    client's two-megabyte response cap while every one of them fits comfortably
    alone, and regrouping the same titles next run would fail identically
    forever. So a failed batch is re-read one title at a time, which turns a
    permanent twenty-page hole into one honestly oversized page.

    That retry is budgeted. When batches keep failing the cause is the wiki or
    the network, not their size, and splitting would multiply a wiki-wide outage
    into twenty times the requests. Past `SPLIT_BUDGET` failures the run stops
    splitting and simply records what it could not read; the next run asks again.
    """
    read: list[census.PageContent] = []
    unreadable = 0
    budget = SPLIT_BUDGET
    for batch in census.batched(titles):
        pages, ok = _read_batch(request, wiki, batch)
        if ok:
            read.extend(pages)
            continue
        if budget <= 0:
            unreadable += len(batch)
            continue
        budget -= 1
        for title in batch:
            single, alone = _read_batch(request, wiki, (title,))
            read.extend(single)
            unreadable += 0 if alone else 1
    return (read, unreadable)


def _known_revisions(session: Session, wiki: str, titles: Sequence[str]) -> dict[str, str]:
    """Revision ids already stored for these titles, so unchanged pages are skipped.

    Tombstoned pages are deliberately left out. A page that was deleted and then
    restored comes back at the revision it left at, so matching on revision alone
    would skip it and leave the directory insisting it is still gone.
    """
    if not titles:
        return {}
    rows = (
        session.query(UserScriptPage.title, UserScriptPage.revision)
        .filter(
            UserScriptPage.wiki == wiki,
            UserScriptPage.title.in_(list(titles)),
            UserScriptPage.deleted_at.is_(None),
        )
        .all()
    )
    return dict(rows)


def _next_rank(session: Session, wiki: str) -> int:
    """One past the highest rank on this wiki, for a page no sweep has ordered yet.

    A page that turned up in recent changes is newer than everything the last
    sweep enumerated, so putting it at the end is not a placeholder -- it is the
    right answer until a sweep confirms it.
    """
    highest = session.query(func.max(UserScriptPage.discovery_rank)).filter(UserScriptPage.wiki == wiki).scalar()
    return int(highest or 0) + 1


def _replace_imports(session: Session, wiki: str, analysis: userscripts.ScriptPage) -> None:
    """Make the stored loads for one page exactly the loads it now makes.

    Replaced rather than merged. An import removed from a page is no longer
    demand, and a row left behind would keep voting for a script whose only
    reader stopped loading it.
    """
    session.query(UserScriptImport).filter(
        UserScriptImport.wiki == wiki,
        UserScriptImport.source_title == analysis.title,
    ).delete(synchronize_session=False)
    # `userscripts.script_imports` already reduces repeated loads to one per
    # (verb, wiki, title, url), which is exactly this table's unique key, so no
    # second pass is needed here.
    for found in analysis.imports:
        session.add(
            UserScriptImport(
                wiki=wiki,
                source_title=analysis.title,
                verb=found.verb,
                target_wiki=found.wiki,
                target_title=found.title,
                target_url=found.url[:MAX_STORED_URL],
                is_stylesheet=found.is_stylesheet,
            ),
        )


def store_page(session: Session, wiki: str, page: census.PageContent, rank: int | None) -> None:
    """Write one observed page, its analysis, and the loads it makes."""
    analysis = userscripts.analyze(page.title, page.body, wiki=wiki)
    row = (
        session.query(UserScriptPage)
        .filter(UserScriptPage.wiki == wiki, UserScriptPage.title == analysis.title)
        .one_or_none()
    )
    if row is None:
        row = UserScriptPage(wiki=wiki, title=analysis.title, first_seen_at=utcnow())
        row.discovery_rank = _next_rank(session, wiki) if rank is None else rank
        session.add(row)
    elif rank is not None:
        row.discovery_rank = rank
    # Safe here and nowhere else: every title that reaches this function came
    # from a namespace-2 search or a namespace-2 recent-changes filter.
    row.owner = owner_of_user_page(analysis.title)
    row.basename = basename_of(analysis.title)
    row.content_model = page.model
    row.role = analysis.role
    row.fingerprint = analysis.fingerprint
    row.body = page.body[:MAX_STORED_BODY]
    row.size_bytes = len(page.body.encode("utf-8", "replace"))
    row.revision = page.revision
    row.touched_at_wiki = page.touched
    row.last_checked_at = utcnow()
    row.deleted_at = None
    session.flush()
    _replace_imports(session, wiki, analysis)


def ingest(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    titles: Sequence[str],
    *,
    ranked: bool,
) -> dict[str, int]:
    """Read the named pages and write the ones that changed.

    `ranked` says whether the caller's ordering is creation order. A sweep's is;
    a watch's is not, and its pages keep whatever order they already had.
    """
    summary = dict(EMPTY_COUNTS, asked=len(titles))
    with db.session_scope() as session:
        known = _known_revisions(session, wiki, [userscripts.canonical_title(title) for title in titles])
    ranks = {userscripts.canonical_title(title): index for index, title in enumerate(titles)} if ranked else {}
    pages, summary["unreadable"] = read_titles(request, wiki, titles)
    summary["fetched"] = len(pages)
    with db.session_scope() as session:
        for page in pages:
            title = userscripts.canonical_title(page.title)
            rank = ranks.get(title)
            unchanged = known.get(title) == page.revision
            if unchanged and (rank is None or rank == _stored_rank(session, wiki, title)):
                summary["skipped"] += 1
                continue
            store_page(session, wiki, page, rank)
            summary["written"] += 1
    return summary


def _stored_rank(session: Session, wiki: str, title: str) -> int | None:
    """Read the rank already recorded for one page, or None when it has no row."""
    return (
        session.query(UserScriptPage.discovery_rank)
        .filter(UserScriptPage.wiki == wiki, UserScriptPage.title == title)
        .scalar()
    )


def _state(session: Session, wiki: str) -> UserScriptCensusState:
    """Fetch the census state row for one wiki, creating it on first sight."""
    row = session.get(UserScriptCensusState, wiki)
    if row is None:
        row = UserScriptCensusState(wiki=wiki)
        session.add(row)
        session.flush()
    return row


def _mark_missing(session: Session, wiki: str, seen: Iterable[str]) -> int:
    """Tombstone the pages a complete enumeration no longer lists."""
    known = set(seen)
    missing = (
        session.query(UserScriptPage).filter(UserScriptPage.wiki == wiki, UserScriptPage.deleted_at.is_(None)).all()
    )
    gone = [row for row in missing if row.title not in known]
    for row in gone:
        row.deleted_at = utcnow()
    return len(gone)


def _record_totals(session: Session, wiki: str) -> UserScriptCensusState:
    """Refresh the cached counts on a wiki's state row from what is stored."""
    state = _state(session, wiki)
    live = (UserScriptPage.wiki == wiki, UserScriptPage.deleted_at.is_(None))
    state.pages_known = session.query(UserScriptPage).filter(*live).count()
    scripts = session.query(UserScriptPage).filter(*live, UserScriptPage.role == userscripts.ROLE_SCRIPT)
    state.scripts_known = scripts.count()
    state.imports_known = session.query(UserScriptImport).filter(UserScriptImport.wiki == wiki).count()
    return state


def sweep(request: Callable[[str, str, dict[str, Any]], Any], wiki: str, *, limit: int = 0) -> dict[str, Any]:
    """Walk a wiki's whole script corpus into the directory."""
    with db.session_scope() as session:
        state = _state(session, wiki)
        state.status = "running"
        state.last_started_at = utcnow()
        state.last_error = ""
    titles, totals, complete = discover(request, wiki)
    truncated = bool(limit) and limit < len(titles)
    if truncated:
        titles = titles[:limit]
    summary = ingest(request, wiki, titles, ranked=True)
    with db.session_scope() as session:
        # A partial walk says nothing about the pages it never asked for, so it
        # is never allowed to declare them gone.
        whole_wiki = complete and not truncated
        removed = _mark_missing(session, wiki, map(userscripts.canonical_title, titles)) if whole_wiki else 0
        state = _record_totals(session, wiki)
        state.enumeration_totals = totals
        state.enumeration_complete = whole_wiki
        state.sweeps_completed += 1
        state.status = "idle"
        state.last_success_at = utcnow()
    return {"wiki": wiki, "mode": "sweep", "complete": complete, "totals": totals, "removed": removed, **summary}


def latest_timestamp(payload: object, fallback: str) -> str:
    """Find the newest change timestamp in one feed, falling back to the old cursor."""
    query = payload.get("query") if isinstance(payload, dict) else None
    changes = query.get("recentchanges") if isinstance(query, dict) else None
    if not isinstance(changes, list):
        return fallback
    stamps = [str(item.get("timestamp") or "") for item in changes if isinstance(item, dict)]
    return max((stamp for stamp in stamps if stamp), default=fallback)


def watch(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    *,
    limit: int = WATCH_LIMIT,
) -> dict[str, Any]:
    """Bring a wiki up to date from the changes since the last run.

    The cursor advances only over changes this run actually read. A window that
    was never read is a page the directory never learns changed, so a watch that
    fails leaves the cursor where it was and the next run re-reads it.
    """
    with db.session_scope() as session:
        cursor = _state(session, wiki).changes_cursor
    payload = request(wiki, "GET", census.changes_params(cursor, limit))
    titles = census.read_changes(payload)
    summary = ingest(request, wiki, titles, ranked=False) if titles else dict(EMPTY_COUNTS)
    with db.session_scope() as session:
        state = _record_totals(session, wiki)
        state.changes_cursor = latest_timestamp(payload, cursor)
        state.last_success_at = utcnow()
        cursor = state.changes_cursor
    return {"wiki": wiki, "mode": "watch", "cursor": cursor, **summary}


def run(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    *,
    full: bool = False,
    limit: int = 0,
    watch_limit: int = WATCH_LIMIT,
) -> dict[str, Any]:
    """Sweep or watch one wiki, whichever the wiki's own state calls for.

    A watch is only meaningful once a sweep has established what "unchanged"
    means. A wiki that has never completed one is swept regardless of what the
    caller asked for, because a first watch would otherwise record a handful of
    edits and call the wiki covered.
    """
    with db.session_scope() as session:
        swept = _state(session, wiki).sweeps_completed
    if full or not swept:
        return sweep(request, wiki, limit=limit)
    return watch(request, wiki, limit=watch_limit)
