# SPDX-License-Identifier: GPL-3.0-or-later
"""What each wiki's user-script directory is built from, and how current it is.

The roster this builds is derived data: every number in it comes from tables
that only `userscript_sweep` and the projection modules it calls ever write. So
it changes when the census runs and at no other time, which is why the sweep
refreshes the stored copy at the end of its run rather than a clock doing it on
a schedule of its own. "Regularly" here means "whenever the answer could have
moved", which is the only schedule that is never both late and wasteful.

Splitting this out of `v1_userscripts` is what lets the sweep refresh it: a
blueprint module importing a job and a job importing a blueprint module cannot
both happen, and the coverage record is domain vocabulary rather than routing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from backend import db
from backend import userscript_directory as directory
from backend import v1_common as common
from backend.models import (
    ApiCacheMeta,
    UserScriptCensusState,
    UserScriptDirectoryEntry,
    UserScriptPage,
    utcnow,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

SNAPSHOT_KEY = "userscript_coverage_v1"
#: How long a stored roster is advertised as fresh. The census runs hourly and
#: refreshes this at the end of every run, so a copy older than that means a run
#: was skipped or died -- worth saying out loud, not worth rebuilding for.
SNAPSHOT_MAX_AGE = timedelta(hours=2)
#: The point at which serving stale stops being better than making one visitor
#: wait. Past this the census has not completed a run in most of a day, and the
#: roster is describing a census that no longer exists.
SNAPSHOT_STALE_LIMIT = timedelta(hours=18)
TIERS = (directory.TIER_ACTIVE, directory.TIER_ARCHIVE)


def coverage(s: Session, wiki: str) -> dict[str, Any]:
    """Describe what this wiki's directory is built from, and how current it is.

    Three timestamps, because a census can be stale in three unrelated ways and
    only one of them is about the job still running. `checkedAt` is liveness --
    the last run of any kind -- and it is the one that says nothing at all about
    the data, since a watch stamps it every hour whether the wiki moved or not.
    `sweptAt` is when this wiki's user space was last enumerated and walked, and
    `currentTo` is the wiki's own clock: how far into recent changes the watch
    has read. A directory can be an hour old by `checkedAt`, a month old by
    `sweptAt`, and current to a fortnight ago by `currentTo`, all at once, and a
    reader given only the first would call it fresh.

    Two ways of being partial are reported separately, because they have
    different remedies. `sweepsCompleted` at zero says no full sweep has ever
    finished -- wait for one. `enumerated` being false says the wiki holds more
    script pages than one search pass can walk, so no amount of waiting will
    finish it. `enumeratedBy` names the road behind the counts, which is what
    distinguishes an exact census from one that merely never hit a cap.
    """
    state = s.get(UserScriptCensusState, wiki)
    pages = int(
        s.execute(
            select(func.count(UserScriptPage.id)).where(
                UserScriptPage.wiki == wiki,
                UserScriptPage.deleted_at.is_(None),
            )
        ).scalar()
        or 0
    )
    counts = dict.fromkeys(TIERS, 0)
    for tier, total in s.execute(
        select(UserScriptDirectoryEntry.tier, func.count(UserScriptDirectoryEntry.id))
        .where(UserScriptDirectoryEntry.wiki == wiki)
        .group_by(UserScriptDirectoryEntry.tier)
    ):
        counts[tier] = int(total)
    computed = s.execute(
        select(func.max(UserScriptDirectoryEntry.computed_at)).where(UserScriptDirectoryEntry.wiki == wiki)
    ).scalar()
    return coverage_row(wiki, state, pages, counts, computed)


def coverage_row(
    wiki: str,
    state: UserScriptCensusState | None,
    pages: int,
    counts: dict[str, int],
    computed: datetime | None,
) -> dict[str, Any]:
    """Assemble one wiki's coverage from parts already read.

    Split out so the one-wiki reader and the whole-roster reader below cannot
    drift: they disagree about how to *fetch* the parts, and must not disagree
    about what a coverage record is.
    """
    return {
        "wiki": wiki,
        "pages": pages,
        "sweepsCompleted": int(state.sweeps_completed) if state else 0,
        "sweptAt": common.iso(state.last_started_at) if state else "",
        "currentTo": (state.changes_cursor or "") if state else "",
        "checkedAt": common.iso(state.last_success_at) if state else "",
        "enumerated": bool(state.enumeration_complete) if state else True,
        "enumeratedBy": (state.enumeration_source or "") if state else "",
        "computedAt": common.iso(computed),
        "active": counts.get(directory.TIER_ACTIVE, 0),
        "archive": counts.get(directory.TIER_ARCHIVE, 0),
    }


def build_roster(s: Session) -> list[dict[str, Any]]:
    """Every touched wiki's coverage, in a fixed number of queries.

    `coverage()` costs four queries, which is the right shape for one wiki and
    the wrong one for a thousand. This endpoint used to call it per wiki: at the
    three wikis the census was configured for that was twelve queries and nobody
    noticed, and across every Wikimedia project it is four thousand -- one of
    them a COUNT over a quarter-million-row table, per wiki.

    Grouping the same four reads costs four queries whatever the roster grows
    to. The wikis are still the union of "has census state" and "has directory
    entries", because a wiki can have been swept without projecting anything and
    a projection can outlive the state row that produced it.

    Four queries is not the same as four cheap ones, which is why nothing serves
    this directly any more -- see `snapshot()`.
    """
    states = {row.wiki: row for row in s.execute(select(UserScriptCensusState)).scalars()}
    pages = {
        wiki: int(total)
        for wiki, total in s.execute(
            select(UserScriptPage.wiki, func.count(UserScriptPage.id))
            .where(UserScriptPage.deleted_at.is_(None))
            .group_by(UserScriptPage.wiki)
        )
    }
    counts: dict[str, dict[str, int]] = {}
    for wiki, tier, total in s.execute(
        select(
            UserScriptDirectoryEntry.wiki,
            UserScriptDirectoryEntry.tier,
            func.count(UserScriptDirectoryEntry.id),
        ).group_by(UserScriptDirectoryEntry.wiki, UserScriptDirectoryEntry.tier)
    ):
        counts.setdefault(wiki, {})[tier] = int(total)
    # `.all()` rather than the Result itself: a Result carries `keys()`, so
    # `dict()` reads it as a mapping and fails instead of consuming the rows.
    computed = dict(
        s.execute(
            select(
                UserScriptDirectoryEntry.wiki,
                func.max(UserScriptDirectoryEntry.computed_at),
            ).group_by(UserScriptDirectoryEntry.wiki)
        ).all()
    )
    return [
        coverage_row(wiki, states.get(wiki), pages.get(wiki, 0), counts.get(wiki, {}), computed.get(wiki))
        for wiki in sorted(set(states) | set(counts))
    ]


def snapshot(*, force: bool = False) -> dict[str, Any]:
    """Return the shared cached roster, preferring a stale one to a rebuild.

    The user-script page awaits this before it requests anything else, so
    whatever this costs is the page's time-to-first-content and not a
    background expense. Rebuilding it aggregates four tables, one of them
    holding half a million rows -- measured at 25 seconds against production,
    which is past the point where a browser gives up and the view renders its
    "the request failed" branch instead. That was the reported symptom: not a
    slow directory, a directory that intermittently did not appear at all.

    So a request never rebuilds on the ordinary path. It reads one row, and the
    census stores that row at the end of every run (`refresh()`), which is the
    only moment the answer can have changed. Serving past SNAPSHOT_MAX_AGE is
    deliberate: the roster carries its own timestamps, the page already shows
    them, and a reader looking at an hour-old sweep count is better served than
    one looking at an error.

    A request still rebuilds in two cases: nothing has ever been stored, and
    the stored copy is older than SNAPSHOT_STALE_LIMIT, which bounds how long a
    dead census can freeze the page. The shared lock keeps that to one worker;
    the rest go on serving what they have rather than turning cache contention
    into half a dozen concurrent full scans.
    """
    now = utcnow()
    with db.advisory_lock("userscript-coverage-refresh", timeout_seconds=2) as acquired:
        with db.session_scope() as session:
            cached = session.get(ApiCacheMeta, SNAPSHOT_KEY)
            cached_payload: dict[str, Any] | None = None
            if cached is not None:
                try:
                    decoded = json.loads(cached.value)
                except json.JSONDecodeError:
                    decoded = None
                cached_payload = decoded if isinstance(decoded, dict) else None
            serve_stale = cached is not None and (cached.updated_at >= now - SNAPSHOT_STALE_LIMIT or not acquired)
            if cached_payload is not None and not force and serve_stale:
                return cached_payload
            payload = _payload(build_roster(session), now)
        # Still under the lock, so a racing rebuild cannot overwrite this with
        # an older roster -- but no longer inside the read's transaction, and
        # best-effort besides: see `_remember`.
        if acquired:
            _remember(payload, now)
        return payload


def _payload(results: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Wrap the roster in the shape the endpoint returns it.

    `generatedAt` is part of the stored document rather than read back from the
    cache row's own `updated_at`, so a payload that travels -- to a browser, to
    a 304 validator -- keeps saying when it was true.
    """
    return {
        "count": len(results),
        "results": results,
        "generatedAt": common.iso(now.replace(tzinfo=None)),
    }


def _remember(payload: dict[str, Any], now: datetime) -> None:
    """Store a rebuilt roster without letting a failed store fail the answer.

    The reader's job is to answer; storing the answer is an optimization for
    the next reader. Sharing the request's transaction meant a write that
    raised took the successfully computed payload down with it -- which is
    exactly how this shipped and returned 500 for a roster that was 4.7x over
    `api_cache_meta.value`'s TEXT ceiling. The endpoint should have degraded to
    what it did before the cache existed: correct, and slow.

    Loud, though. A store that keeps failing means every request rebuilds, and
    the rebuild is the 25-second scan this exists to avoid, so the log line is
    the only warning before the page goes back to timing out.
    """
    try:
        with db.session_scope() as session:
            _store(session, payload, now)
    except SQLAlchemyError:
        _log.exception("userscript coverage roster could not be stored; serving rebuilt copy")


def _store(session: Session, payload: dict[str, Any], now: datetime) -> None:
    """Write one rebuilt roster into the shared cache row."""
    cached = session.get(ApiCacheMeta, SNAPSHOT_KEY)
    if cached is None:
        cached = ApiCacheMeta(key=SNAPSHOT_KEY, value="")
        session.add(cached)
    cached.value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    cached.updated_at = now


def refresh() -> dict[str, Any]:
    """Rebuild and store the roster on behalf of the census run that just ended.

    Separate from ``snapshot(force=True)`` because a run that loses the lock
    should stop rather than spend the whole rebuild on a payload it is not
    allowed to store, and because the caller reports whether the stored copy
    moved.

    A failed store raises here, unlike on the read path, and deliberately: a
    reader that cannot cache its answer still has an answer, while a job whose
    only product is the stored row has produced nothing. `userscript_sweep`
    catches it and reports it as the run's own failure.
    """
    now = utcnow()
    with (
        db.advisory_lock("userscript-coverage-refresh", timeout_seconds=2) as acquired,
        db.session_scope() as session,
    ):
        if not acquired:
            return {"stored": False, "wikis": 0, "reason": "another refresh holds the lock"}
        payload = _payload(build_roster(session), now)
        _store(session, payload, now)
        return {"stored": True, "wikis": payload["count"], "generatedAt": payload["generatedAt"]}
