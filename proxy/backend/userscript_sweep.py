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

from sqlalchemy import and_, func, or_, tuple_
from sqlalchemy.exc import IntegrityError

from backend import db, userscripts, wiki_namespaces
from backend import userscript_census as census
from backend import userscript_enumeration as enumeration
from backend.models import UserScriptCensusState, UserScriptImport, UserScriptPage, utcnow
from backend.userscript_directory import basename_of, owner_of_user_page

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from sqlalchemy.orm import Session
    from sqlalchemy.sql.elements import ColumnElement

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


class ReplicationLagged(Exception):  # noqa: N818 - a condition of the wiki, not an error of ours
    """The wiki refused a read because its replicas are behind.

    Its own class because the split in `read_titles` reads a failed batch as
    "too large" and halves it. A `maxlag` refusal fails identically, so without
    this the census would answer the wiki's request for less traffic by making
    about six times as many requests, and burn `SPLIT_BUDGET` doing it. Sending
    `maxlag` without telling the two apart is worse than not sending it at all.
    """


# How many (wiki, title) pairs to name in one IN clause when resolving loads to
# pages. A run writing two thousand pages can hold tens of thousands of loads,
# and one statement naming all of them is a statement no engine should be asked
# to plan; MySQL's max_allowed_packet, not correctness, is what this respects.
RESOLVE_CHUNK: int = 500

EMPTY_COUNTS: dict[str, int] = {
    "asked": 0,
    "fetched": 0,
    "written": 0,
    "skipped": 0,
    "unreadable": 0,
    "resolved": 0,
    #: Set when the wiki refused a read for replication lag. A count elsewhere
    #: says what a run did; this says the run was cut short, which is the only
    #: thing that makes the other counts an incomplete answer rather than a
    #: small one.
    "lagged": 0,
}


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
    """Read one batch of titles, reporting failure rather than raising it.

    Except a lag refusal, which is raised: it is the one failure that says
    something about the wiki rather than about this batch, and the only correct
    answer to it is to stop asking.
    """
    try:
        payload = request(wiki, "GET", census.content_params(batch))
    except Exception as error:
        # Anything else is one gap in the census, never a job failure. The code
        # is read off the exception rather than matched by type because the
        # client normalizes every API refusal into one class.
        if getattr(error, "code", "") == census.MAXLAG_ERROR:
            raise ReplicationLagged(str(error)) from error
        return ((), False)
    return (census.read_pages(payload), True)


def read_titles(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    titles: Sequence[str],
) -> tuple[list[census.PageContent], int, bool]:
    """Fetch and parse pages in API-sized batches, counting the titles left unread.

    A batch can fail for the batch's own sake: fifty user scripts can exceed the
    client's two-megabyte response cap while every one of them fits comfortably
    alone, and regrouping the same titles next run would fail identically
    forever. So a failed batch is halved and each half asked for again, down to
    the single title that is genuinely too big to read. Halving rather than
    going straight to singles is what makes a large `CONTENT_BATCH` worth
    having: one fat page in a batch of fifty costs about six extra requests
    instead of fifty, so the batch size can be set by what the wiki will answer
    rather than by what a bad batch would cost to recover from.

    That retry is budgeted. When batches keep failing the cause is the wiki or
    the network, not their size, and splitting would multiply a wiki-wide outage
    into many times the requests. Past `SPLIT_BUDGET` failures the run stops
    splitting and simply records what it could not read; the next run asks again.

    A lag refusal ends the read there and is reported as the third value. What
    was already read is still returned, because it is already paid for and the
    caller can still write it -- but the titles behind it were never asked for,
    and saying so is what stops the caller from recording them as covered.
    """
    read: list[census.PageContent] = []
    unreadable = 0
    budget = SPLIT_BUDGET
    for batch in census.batched(titles):
        try:
            pages, ok = _read_batch(request, wiki, batch)
            if ok:
                read.extend(pages)
                continue
            if budget <= 0:
                unreadable += len(batch)
                continue
            budget -= 1
            found, lost = _read_halves(request, wiki, batch)
        except ReplicationLagged:
            return (read, unreadable, True)
        read.extend(found)
        unreadable += lost
    return (read, unreadable, False)


def _read_halves(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    batch: Sequence[str],
) -> tuple[list[census.PageContent], int]:
    """Re-read a failed batch by halving it, returning what came back and what did not.

    A single title that fails has nothing left to divide, and is the honestly
    oversized -- or deleted, or otherwise unreadable -- page the split was
    looking for. It is counted, not raised: per this module, a page that cannot
    be read is an observation.
    """
    if len(batch) <= 1:
        return ([], len(batch))
    read: list[census.PageContent] = []
    unreadable = 0
    middle = len(batch) // 2
    for half in (batch[:middle], batch[middle:]):
        pages, ok = _read_batch(request, wiki, half)
        if ok:
            read.extend(pages)
            continue
        found, lost = _read_halves(request, wiki, half)
        read.extend(found)
        unreadable += lost
    return (read, unreadable)


def _stored_state(session: Session, wiki: str, titles: Sequence[str]) -> dict[str, tuple[str, int]]:
    """Revision id and discovery rank already stored for each of these titles.

    Both together, in one statement, because both decide whether a page needs
    writing and asking per page cost one SELECT per page of every sweep.

    Tombstoned pages are deliberately left out. A page that was deleted and then
    restored comes back at the revision it left at, so matching on revision alone
    would skip it and leave the directory insisting it is still gone.
    """
    if not titles:
        return {}
    rows = (
        session.query(UserScriptPage.title, UserScriptPage.revision, UserScriptPage.discovery_rank)
        .filter(
            UserScriptPage.wiki == wiki,
            UserScriptPage.title.in_(list(titles)),
            UserScriptPage.deleted_at.is_(None),
        )
        .all()
    )
    return {title: (revision, rank) for title, revision, rank in rows}


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
    rows = [
        {
            "wiki": wiki,
            "source_title": analysis.title,
            "verb": found.verb,
            "target_wiki": found.wiki,
            "target_title": found.title,
            "target_url": found.url[:MAX_STORED_URL],
            "is_stylesheet": found.is_stylesheet,
        }
        for found in analysis.imports
    ]
    # `userscripts.script_imports` has already reduced repeated loads to one per
    # (verb, wiki, title, url), but that is Python's idea of one, not this
    # table's. Python compares these strings byte by byte; MySQL compares them
    # under a collation that folds case and ignores invisible marks, so two
    # loads Python calls distinct can be one row to the database -- User:.../
    # global.js on Meta loads both `MediaWiki:Gadget-LinkTranslator.js` and
    # `Mediawiki:gadget-LinkTranslator.js`, which are the same page and the same
    # key. Predicting the fold is the wrong repair: it means restating a
    # collation this code cannot see, and the tests run on SQLite, which
    # compares bytes and so can never disagree with a prediction. So the
    # database decides what a duplicate is. A page whose loads all survive costs
    # one savepoint; only a page that actually collides is retried a row at a
    # time, and the row that loses is dropped rather than raised -- one page's
    # spelling is not a reason to fail the wiki, per this module's contract.
    if _insert_all(session, rows):
        return
    for row in rows:
        _insert_all(session, [row])


def _insert_all(session: Session, rows: Sequence[dict[str, Any]]) -> bool:
    """Add `rows` in one savepoint, reporting whether the database accepted them.

    A rejected savepoint rolls back only these rows; the surrounding session --
    the page, its analysis, the sweep's cursor -- survives, which is the whole
    reason for the nesting. The rows are passed as field values rather than as
    instances because a rollback expunges whatever the savepoint added, and the
    retry needs objects that were never in the failed transaction.
    """
    try:
        with session.begin_nested():
            session.add_all(UserScriptImport(**row) for row in rows)
            session.flush()
    except IntegrityError:
        return False
    return True


def store_page(
    session: Session,
    wiki: str,
    page: census.PageContent,
    rank: int | None,
    spellings: userscripts.Spellings = userscripts.no_spellings,
) -> None:
    """Write one observed page, its analysis, and the loads it makes.

    `spellings` resolves any wiki's user-namespace names, not just this one's.
    A load edge names its target wiki, and folding that target's title needs the
    target's namespace names -- `Benutzer:` is namespace 2 on dewiki and an
    ordinary page title everywhere else.
    """
    analysis = userscripts.analyze(page.title, page.body, wiki=wiki, spellings=spellings)
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


def ingest(  # noqa: PLR0913 - the two ranking arguments and the revision map are all one caller's context
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    titles: Sequence[str],
    *,
    ranked: bool,
    rank_offset: int = 0,
    revisions: dict[str, str] | None = None,
) -> dict[str, int]:
    """Read the named pages and write the ones that changed.

    `revisions` is what the caller already knows about the wiki's current
    revision ids, before a single page has been asked for. The replica road
    hands over the whole enumeration's worth, and every page it settles is a
    content request never made -- which is the entire cost of a sweep. Omitted,
    or empty from a road that cannot say, every page is fetched as before.

    `ranked` says whether the caller's ordering is creation order. A sweep's is;
    a watch's is not, and its pages keep whatever order they already had.

    `rank_offset` is where these titles begin in that ordering. A sweep that
    covers a wiki in several runs hands over a slice, and a slice numbered from
    zero would tell the directory that the ten thousandth page ever created was
    the first -- so the rank recorded is the position in the whole enumeration,
    not the position in the batch.
    """
    summary = dict(EMPTY_COUNTS, asked=len(titles))
    written: list[str] = []
    with db.session_scope() as session:
        # This wiki's own names, read once. Every title in `titles` came from
        # this wiki's enumeration, so they all fold under the same set.
        local = wiki_namespaces.resolver(session, request)(wiki)
        stored = _stored_state(session, wiki, [userscripts.canonical_title(title, spellings=local) for title in titles])
    ranks = (
        {userscripts.canonical_title(title, spellings=local): rank_offset + index for index, title in enumerate(titles)}
        if ranked
        else {}
    )
    ahead = revisions or {}
    wanted = [
        title
        for title in titles
        if not _settled(userscripts.canonical_title(title, spellings=local), stored, ranks, ahead)
    ]
    summary["skipped"] = len(titles) - len(wanted)
    pages, summary["unreadable"], lagged = read_titles(request, wiki, wanted)
    summary["lagged"] = int(lagged)
    summary["fetched"] = len(pages)
    with db.session_scope() as session:
        # A fresh resolver: the one above belongs to a session that has closed.
        # Its memo is what keeps a sweep to one siteinfo request per wiki it
        # meets, however many thousands of edges name that wiki.
        spellings = wiki_namespaces.resolver(session, request)
        for page in pages:
            title = userscripts.canonical_title(page.title, spellings=local)
            rank = ranks.get(title)
            if _settled(title, stored, ranks, {title: page.revision}):
                summary["skipped"] += 1
                continue
            store_page(session, wiki, page, rank, spellings)
            written.append(title)
            summary["written"] += 1
        summary["resolved"] = resolve_targets(session, wiki, written)
    return summary


def _settled(
    title: str,
    stored: dict[str, tuple[str, int]],
    ranks: dict[str, int],
    revisions: dict[str, str],
) -> bool:
    """Whether this page is already stored exactly as this run would store it.

    Two things have to agree. The revision says the body has not moved; the rank
    says the page still sits where this enumeration puts it, which a page can
    fail while its body is untouched -- delete a page created before it and
    everything after shifts up.

    `revisions` is whatever the caller can say about the current revision at the
    moment it asks. From the replica it is the whole enumeration, known before
    any page is fetched, and a page that settles here is a request never made.
    From a fetched page it is that one page, and settling only saves the write.
    A title absent from it is never settled: not knowing the current revision is
    not evidence that it matches.
    """
    current = revisions.get(title)
    if not current:
        return False
    known = stored.get(title)
    if known is None or known[0] != current:
        return False
    rank = ranks.get(title)
    return rank is None or rank == known[1]


def page_ids(session: Session, targets: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """Read the page id for each (wiki, title) we hold, skipping the ones we do not."""
    found: dict[tuple[str, str], int] = {}
    for chunk in _chunked(sorted(set(targets))):
        rows = session.query(UserScriptPage.wiki, UserScriptPage.title, UserScriptPage.id).filter(
            tuple_(UserScriptPage.wiki, UserScriptPage.title).in_(chunk)
        )
        found.update({(wiki, title): page_id for wiki, title, page_id in rows})
    return found


def _chunked(items: Sequence[Any], size: int = RESOLVE_CHUNK) -> Iterable[Sequence[Any]]:
    """Cut a list into pieces small enough to name in one IN clause."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _target_wiki(row: UserScriptImport) -> str:
    """Which wiki a load points at, given that naming none means naming its own."""
    return row.target_wiki or row.wiki


def _targets_wiki(wiki: str) -> ColumnElement[bool]:
    """Match loads that land on `wiki`, however the row happened to say so."""
    return or_(
        UserScriptImport.target_wiki == wiki,
        and_(UserScriptImport.target_wiki == "", UserScriptImport.wiki == wiki),
    )


def resolve_targets(session: Session, wiki: str, written: Sequence[str]) -> int:
    """Point this run's loads at the pages they name, both directions.

    A run creates resolvable edges two ways, and only doing one of them would
    leave the graph permanently half-built. The pages it wrote have loads of
    their own, whose targets may be pages stored long ago; and pages stored
    long ago may hold loads that were waiting for exactly the pages this run
    has just written. So both are resolved, scoped to this run's titles.

    Scoping matters more than it looks. The obvious implementation -- sweep
    every row where `target_page_id` is null -- re-reads the same unresolvable
    rows on every run forever, because a load pointing at a wiki outside the
    census never becomes resolvable and never stops being scanned. Driving from
    what changed means the work is proportional to the run, not to the corpus.
    """
    if not written:
        return 0
    resolved = 0
    for chunk in _chunked(written):
        # Loads made *by* the pages this run wrote.
        outbound = session.query(UserScriptImport).filter(
            UserScriptImport.wiki == wiki,
            UserScriptImport.source_title.in_(chunk),
            UserScriptImport.target_title != "",
        )
        # Loads made *of* the pages this run wrote, from anywhere -- including
        # the ones that named no wiki at all, which mean the one they sit on.
        inbound = session.query(UserScriptImport).filter(
            _targets_wiki(wiki),
            UserScriptImport.target_title.in_(chunk),
            UserScriptImport.target_page_id.is_(None),
        )
        rows = list(outbound) + list(inbound)
        ids = page_ids(session, ((_target_wiki(row), row.target_title) for row in rows))
        for row in rows:
            page_id = ids.get((_target_wiki(row), row.target_title))
            if page_id is not None and row.target_page_id != page_id:
                row.target_page_id = page_id
                resolved += 1
    return resolved


def resolve_pending(session: Session, wiki: str) -> int:
    """Resolve every load into this wiki that names a page we already hold.

    `resolve_targets` is scoped to one run's titles, which is right for a sweep
    and wrong for a reader. Anything that counts demand by identity needs the
    edges it can see to already be resolved, and it has no way of knowing which
    run should have done it -- rows written before the column existed, or while
    a sweep was interrupted, would simply be missing, and missing demand reads
    as a quiet directory rather than as an error.

    So this repairs its own input before use. It is not the null scan
    `resolve_targets` deliberately avoids: the join *is* the bound, and a load
    pointing outside the census matches no page and is never updated. Only rows
    that can resolve are touched, so on a healthy corpus it writes nothing.
    """
    rows = (
        session.query(UserScriptImport, UserScriptPage.id)
        .join(
            # The filter below already pins the effective target wiki to `wiki`,
            # so the page only has to match on title.
            UserScriptPage,
            and_(UserScriptPage.wiki == wiki, UserScriptPage.title == UserScriptImport.target_title),
        )
        .filter(
            _targets_wiki(wiki),
            UserScriptImport.target_title != "",
            UserScriptImport.target_page_id.is_(None),
        )
        .all()
    )
    for row, page_id in rows:
        row.target_page_id = page_id
    return len(rows)


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
    which is some 3,100 content requests at `CONTENT_BATCH` 50 -- more than one
    scheduled job should hold a wiki's API budget for. So a bounded run reads its slice, records how
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
    summary = ingest(request, wiki, window, ranked=True, rank_offset=start, revisions=found.revisions)
    # A wiki that asked us to stop was not covered to the end of the window, and
    # the cursor is the only record of that. Holding it re-asks this window next
    # run rather than stepping over pages nobody read -- and re-asking is nearly
    # free, because what did get written now matches the revision the
    # enumeration reports and is skipped before a request is spent on it.
    if summary["lagged"]:
        finished = False
    with db.session_scope() as session:
        # A partial walk says nothing about the pages it never asked for, so it
        # is never allowed to declare them gone. Tombstoning compares against the
        # whole enumeration rather than this run's slice: by the time a bounded
        # sweep finishes, the full list is what it has covered.
        whole_wiki = found.complete and finished
        # Read, not refreshed: `ingest` has already been through this wiki and
        # brought its spellings up to date, so a second request here would only
        # confirm what the row above it says.
        local = wiki_namespaces.resolver(session)(wiki)
        seen = (userscripts.canonical_title(title, spellings=local) for title in found.titles)
        removed = _mark_missing(session, wiki, seen) if whole_wiki else 0
        state = _record_totals(session, wiki)
        state.enumeration_totals = found.totals
        state.enumeration_complete = whole_wiki
        state.enumeration_source = found.source
        state.sweep_cursor = cursor if summary["lagged"] else (0 if finished else start + len(window))
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
        # Same rule as the sweep cursor: a watch cut short by lag has not read
        # the changes it enumerated, and advancing over them would lose the
        # edits for good -- a watch has no second pass to find them again.
        state.changes_cursor = cursor if summary["lagged"] else latest_timestamp(payload, cursor)
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

    A completed sweep is not permanent either, and this is the case that has to
    be looked for rather than waited for. Discovery has two roads, the exact one
    is not always reachable, and a wiki that finished on the capped one keeps
    that census for good -- nothing about watching for changes ever revisits
    what the wiki was found to hold. frwiki did exactly this: swept from the
    search index the day before the replica road landed, 920 pages short, and
    watching contentedly ever since. So a census whose recorded road has since
    been superseded is swept again. It cannot become a loop, because the sweep
    writes down the road it actually got: a host where the replica keeps failing
    records that it fell back, and `enumeration.superseded` leaves it alone.
    """
    with db.session_scope() as session:
        state = _state(session, wiki)
        swept, pending = state.sweeps_completed, state.sweep_cursor
        outdated = enumeration.superseded(state.enumeration_source)
    if full or not swept or pending or outdated:
        return sweep(request, wiki, limit=limit)
    return watch(request, wiki, limit=watch_limit)
