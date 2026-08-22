# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading one wiki's user scripts into the directory, and keeping them current.

Two passes over the same machinery. A *sweep* walks every page of a script
content model, in creation order, and is how a wiki first enters the directory
-- `backend.userscript_enumeration` decides where that list comes from. A
*watch* follows recent changes since the last run, and is how it stays current.
Between them they are the difference between a census and a directory.

A sweep need not fit in one run. enwiki holds around 155,000 script pages, and
`limit` bounds what a single run reads; the wiki's `sweep_cursor` carries the
position forward so successive runs cover the corpus instead of re-reading its
first slice, and only the run that reaches the end declares the sweep done.

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
from backend import userscript_enumeration as enumeration
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


def discover(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
) -> enumeration.Enumeration:
    """Every script-model title on a wiki, in creation order, with per-model totals.

    Order matters and is not incidental: both roads in
    `backend.userscript_enumeration` return creation order, so the position of a
    title in this sequence is the only creation ordering the directory needs,
    obtained without a single extra request.
    """
    return enumeration.enumerate_wiki(request, wiki)


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
    # second pass is needed here. That holds only while every title and URL
    # reaching it is already in storage's spelling, which is what the format-mark
    # strip in `canonical_title` and `_resolve` is for: Python compares these
    # strings byte by byte, MySQL compares them under a collation that ignores
    # invisible marks, and where the two disagree it is this INSERT that fails
    # and takes the whole wiki's ingest down with it. The tests run on SQLite,
    # which compares bytes, so they cannot be the thing that catches a new gap.
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
    rank_offset: int = 0,
) -> dict[str, int]:
    """Read the named pages and write the ones that changed.

    `ranked` says whether the caller's ordering is creation order. A sweep's is;
    a watch's is not, and its pages keep whatever order they already had.

    `rank_offset` is where these titles begin in that ordering. A sweep that
    covers a wiki in several runs hands over a slice, and a slice numbered from
    zero would tell the directory that the ten thousandth page ever created was
    the first -- so the rank recorded is the position in the whole enumeration,
    not the position in the batch.
    """
    summary = dict(EMPTY_COUNTS, asked=len(titles))
    with db.session_scope() as session:
        known = _known_revisions(session, wiki, [userscripts.canonical_title(title) for title in titles])
    ranks = (
        {userscripts.canonical_title(title): rank_offset + index for index, title in enumerate(titles)}
        if ranked
        else {}
    )
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


def _resume_from(cursor: int, found: enumeration.Enumeration) -> int:
    """Where in this enumeration to pick up, given where the last run stopped.

    A cursor is a position in a list, and it means nothing against a different
    list. A capped search returns a prefix whose length depends on what the
    index will serve, so a cursor into one is dropped; so is a cursor that now
    points past the end, which is what a wiki that shrank between runs looks
    like. Both restart the wiki from the beginning, which costs a pass and
    cannot silently skip pages.
    """
    return cursor if found.complete and 0 < cursor < len(found.titles) else 0


def sweep(request: Callable[[str, str, dict[str, Any]], Any], wiki: str, *, limit: int = 0) -> dict[str, Any]:
    """Walk a wiki's script corpus into the directory, over as many runs as it takes.

    `limit` bounds one run, not the census. enwiki holds ~155,000 script pages,
    which is some 7,800 content requests -- more than one scheduled job should
    hold a wiki's API budget for. So a bounded run reads its slice, records how
    far it got, and the next run continues from there; only the run that reaches
    the end of the enumeration counts as a completed sweep, tombstones what the
    wiki no longer lists, and lets the wiki fall through to watching.
    """
    with db.session_scope() as session:
        state = _state(session, wiki)
        state.status = "running"
        state.last_started_at = utcnow()
        state.last_error = ""
        cursor = state.sweep_cursor
    found = discover(request, wiki)
    start = _resume_from(cursor, found)
    window = found.titles[start : start + limit] if limit else found.titles[start:]
    finished = start + len(window) >= len(found.titles)
    summary = ingest(request, wiki, window, ranked=True, rank_offset=start)
    with db.session_scope() as session:
        # A partial walk says nothing about the pages it never asked for, so it
        # is never allowed to declare them gone. Tombstoning compares against the
        # whole enumeration rather than this run's slice: by the time a bounded
        # sweep finishes, the full list is what it has covered.
        whole_wiki = found.complete and finished
        seen = map(userscripts.canonical_title, found.titles)
        removed = _mark_missing(session, wiki, seen) if whole_wiki else 0
        state = _record_totals(session, wiki)
        state.enumeration_totals = found.totals
        state.enumeration_complete = whole_wiki
        state.sweep_cursor = 0 if finished else start + len(window)
        state.sweeps_completed += 1 if finished else 0
        state.status = "idle"
        state.last_success_at = utcnow()
        cursor = state.sweep_cursor
    # Named `sweep_cursor` rather than `cursor` because a watch already reports
    # one under that name and it is a different thing entirely -- a recent-changes
    # timestamp, not a position in an enumeration.
    return {
        "wiki": wiki,
        "mode": "sweep",
        "complete": found.complete,
        "source": found.source,
        "totals": found.totals,
        "enumerated": len(found.titles),
        "sweep_cursor": cursor,
        "removed": removed,
        **summary,
    }


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
    edits and call the wiki covered. A wiki part-way through a bounded sweep is
    in the same position for the same reason, and keeps sweeping until the
    cursor comes back to zero.
    """
    with db.session_scope() as session:
        state = _state(session, wiki)
        swept, pending = state.sweeps_completed, state.sweep_cursor
    if full or not swept or pending:
        return sweep(request, wiki, limit=limit)
    return watch(request, wiki, limit=watch_limit)
