# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the page a user script's author wrote its documentation on.

A user script has no description here and will not get one: this lane
transcribes what a wiki says and does not read prose. Documentation is a
different question. MediaWiki's own title rules put `User:Lupin/popups.js`
under `User:Lupin/popups`, and by long convention that is where the author
writes what the script does and how to install it. The convention is the wiki's,
not this codebase's, so asking whether that page exists is a transcription too
-- the answer is a link somebody already published, not a sentence anybody here
made up.

The base page is asked for, never assumed. Existence is the whole test, and it
is asked of the wiki 50 titles at a time, which is the API's ceiling for an
account without raised limits. Redirects are followed, because the convention
survives a rename: `User:Ale jrb/Scripts/igloo` is a redirect to
`Wikipedia:Igloo`, and the redirect is the author saying where the documentation
moved to. Publishing the redirect rather than its target would send a reader
one hop short of the page they wanted.

The base page must be a subpage. `User:Someone.js` bases to `User:Someone`,
which is an account's own page: it always exists, it is never documentation,
and treating it as such would give every such script a link to its author
instead of to itself. That is worse than no link at all, which is the standing
rule in this lane -- a `user_docs_url` is a thing a reader clicks.

The answer is stored on `UserScriptPage` rather than on the directory entry,
because `userscript_projection` deletes and rebuilds directory rows per wiki and
a fact that cost a request would be thrown away on every run. `docs_checked_at`
is what stops it being asked again on the next run: without it every run would
re-ask the wiki about every page it already has an answer for, which for enwiki
alone is several hundred requests an hour, forever.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import or_, select

from backend import db, userscripts
from backend.models import UserScriptPage, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session

# Titles per request. The API's own ceiling on `titles` for an account without
# raised limits, and this query carries no content, so the response stays small
# whatever the pages behind those titles hold.
TITLE_BATCH: Final = 50

# Rows read per transaction. Ten requests' worth, so a wiki is walked in
# database chunks large enough that paging is not the cost.
BATCH: Final = 500

# Requests one wiki may spend on this in a single run. A wiki that has never
# been asked converges over a few runs rather than crowding out the census it
# runs beside -- enwiki's user space is tens of thousands of pages and this is
# the least urgent thing the sweep does.
MAX_REQUESTS: Final = 200

# How long an answer stands before the wiki is asked again. Documentation gets
# written after the script it documents, so "no page" has to be a question this
# lane can put again; a month is slow enough to cost nothing and fast enough
# that a page written today is catalogued this cycle rather than never.
RECHECK_DAYS: Final = 30

# Seconds of replication lag past which the wiki should refuse us rather than
# serve a slow answer, matching every other bulk reader in this lane.
MAXLAG_SECONDS: Final = 5

# Suffixes a code page carries, stripped to get the page beside it.
SUFFIXES: Final = (".js", ".css", ".json")

# Redirect hops followed before giving up. A title is normalized once and
# redirected once, so anything past this is a loop the wiki should not have.
MAX_HOPS: Final = 4

COUNT_FIELDS: Final = ("asked", "checked", "found", "written", "requests")


def base_title(title: str) -> str:
    """Return the page beside one code page, or "" if it has no usable one.

    Two pages get nothing. A title with no code suffix is not a script page and
    has no page beside it. A title whose base is not a subpage bases to an
    account's own page, which exists for every author and documents nothing --
    see the module docstring.
    """
    text = str(title or "").strip()
    folded = text.casefold()
    base = next((text[: -len(suffix)] for suffix in SUFFIXES if folded.endswith(suffix)), "")
    if not base:
        return ""
    _owner, slash, subpage = base.partition("/")
    return base if slash and subpage.strip() else ""


def params(titles: Sequence[str]) -> dict[str, Any]:
    """Parameters asking only whether each of up to TITLE_BATCH pages exists.

    No `prop` is requested. The bare query already answers the only question --
    a title the wiki has no page for comes back with `missing: true` -- and
    asking for nothing keeps a batch of 50 to a couple of kilobytes.
    """
    return {
        "action": "query",
        "titles": "|".join(titles[:TITLE_BATCH]),
        "redirects": 1,
        "maxlag": MAXLAG_SECONDS,
    }


def _links(query: dict[str, Any]) -> dict[str, str]:
    """Return every from/to hop the wiki reported, normalizations and redirects alike."""
    hops: dict[str, str] = {}
    for key in ("normalized", "redirects"):
        listed = query.get(key)
        if not isinstance(listed, list):
            continue
        for item in listed:
            if isinstance(item, dict) and item.get("from") and item.get("to"):
                hops[str(item["from"])] = str(item["to"])
    return hops


def _existing(query: dict[str, Any]) -> set[str]:
    pages = query.get("pages")
    if not isinstance(pages, list):
        return set()
    return {
        str(page.get("title") or "")
        for page in pages
        if isinstance(page, dict) and not page.get("missing") and page.get("pageid")
    }


def resolved(payload: object, asked: Sequence[str]) -> dict[str, str]:
    """Return, for each asked title that exists, the title it actually resolves to.

    A title the wiki spells differently, and a title that redirects, are both
    followed to whatever the wiki finally answered about -- so what comes back
    is the page a reader would land on, which is the only page worth publishing.
    A title that resolves to something the wiki has no page for is absent, not
    empty: this returns what was found, and everything else is unanswered.
    """
    query = payload.get("query") if isinstance(payload, dict) else None
    if not isinstance(query, dict):
        return {}
    hops, exists = _links(query), _existing(query)
    found: dict[str, str] = {}
    for title in asked:
        current = title
        for _hop in range(MAX_HOPS):
            following = hops.get(current)
            if following is None:
                break
            current = following
        if current in exists:
            found[title] = current
    return found


def batched(titles: Sequence[str], size: int = TITLE_BATCH) -> Iterable[tuple[str, ...]]:
    """Split titles into request-sized groups, skipping nothing."""
    for start in range(0, len(titles), size):
        yield tuple(titles[start : start + size])


def pending(session: Session, wiki: str, after: int, stale_before: datetime) -> tuple[tuple[int, str], ...]:
    """Read the id and title of the next pages of one wiki whose answer has expired.

    Only script pages, and only ones the census still sees. A shim or a stub is
    somebody's one-line loader and has no documentation of its own, and a page
    that has been deleted has nothing left to document.

    Ids and titles rather than rows, because the wiki is asked between reading
    this and writing the answer, and a request is not a thing to hold a
    transaction open across.
    """
    rows = session.execute(
        select(UserScriptPage.id, UserScriptPage.title)
        .where(
            UserScriptPage.wiki == wiki,
            UserScriptPage.role == userscripts.ROLE_SCRIPT,
            UserScriptPage.deleted_at.is_(None),
            or_(UserScriptPage.docs_checked_at.is_(None), UserScriptPage.docs_checked_at < stale_before),
            UserScriptPage.id > after,
        )
        .order_by(UserScriptPage.id)
        .limit(BATCH)
    ).all()
    return tuple((int(row_id), str(title or "")) for row_id, title in rows)


def apply_docs(session: Session, found: dict[int, str], checked: Sequence[int], now: datetime) -> int:
    """Stamp the answer onto every page asked about. Returns how many answers moved.

    Every page asked about is stamped as checked, including the ones with no
    documentation page: "asked, and the wiki said no" is exactly the answer that
    stops it being asked again next hour. What is counted is what changed, in
    either direction -- a page that gained documentation and a page whose
    documentation was deleted are both news, and a re-check that confirms what
    was already stored is not.
    """
    if not checked:
        return 0
    written = 0
    for row in session.execute(select(UserScriptPage).where(UserScriptPage.id.in_(checked))).scalars():
        title = found.get(row.id, "")
        if row.docs_title != title:
            row.docs_title = title
            written += 1
        row.docs_checked_at = now
    return written


def resolve(
    request: Callable[[str, str, dict[str, Any]], Any],
    wiki: str,
    *,
    limit: int = MAX_REQUESTS,
) -> dict[str, int]:
    """Ask one wiki which of its script pages have a documentation page beside them.

    Best effort, as every wiki reader in this lane is. A wiki that refuses --
    lagged replicas, a timeout, anything -- ends this step early with what it
    already wrote kept, because per `backend.job_contract` a source that was
    unavailable for one run is an observation and not a job failure, and the
    census this runs beside has already done its real work.

    Paged by id rather than by re-asking what is still unanswered, for the same
    reason `userscript_creation_dates` is: a page whose answer this run failed
    to write would come back in every batch of a "what is still missing" loop,
    and the loop would never end.
    """
    counts = dict.fromkeys(COUNT_FIELDS, 0)
    now = utcnow()
    stale_before = now - timedelta(days=RECHECK_DAYS)
    after = 0
    while counts["requests"] < limit:
        with db.session_scope() as session:
            batch = pending(session, wiki, after, stale_before)
        if not batch:
            break
        after = batch[-1][0]
        counts["asked"] += len(batch)
        # A page whose title bases to nothing is settled without a request: the
        # answer cannot change, and it still gets stamped so it is not re-read.
        bases = {row_id: base for row_id, title in batch if (base := base_title(title))}
        by_title: dict[str, list[int]] = {}
        for row_id, base in bases.items():
            by_title.setdefault(base, []).append(row_id)
        found: dict[int, str] = {}
        answered: set[str] = set()
        stopped = False
        for chunk in batched(sorted(by_title)):
            if counts["requests"] >= limit:
                stopped = True
                break
            counts["requests"] += 1
            try:
                payload = request(wiki, "GET", params(chunk))
            except Exception:  # noqa: BLE001 - one wiki's outage is not this job's failure
                stopped = True
                break
            answered.update(chunk)
            for asked, target in resolved(payload, chunk).items():
                for row_id in by_title.get(asked, ()):
                    found[row_id] = target
        # Only pages the wiki was actually asked about are stamped. A batch cut
        # short by the request cap or by a refusal leaves the rest untouched, so
        # the next run asks them rather than this one recording a silent "no
        # documentation" for a question nobody put. A page that bases to nothing
        # is stamped either way: no request could change that answer.
        settled = [row_id for row_id, title in batch if row_id not in bases or bases[row_id] in answered]
        counts["checked"] += len(settled)
        counts["found"] += len(found)
        with db.session_scope() as session:
            counts["written"] += apply_docs(session, found, settled, now)
        if stopped:
            break
    return counts
