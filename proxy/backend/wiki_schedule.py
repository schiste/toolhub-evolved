# SPDX-License-Identifier: GPL-3.0-or-later
"""Deciding which wikis a census run covers, and stopping it before it overruns.

A lane that covered every configured wiki on every tick was a schedule only
because the list had three entries. Across a thousand wikis no run can cover
everything, so the question stops being "which wikis are configured" and becomes
"which wikis are owed a turn, and how much of this run is left".

Both halves are deliberately not counts.

The queue is owed-ness, not position: each wiki carries when it is next due, the
run takes the most overdue first, and a wiki that was skipped last time is
simply more overdue now. Nothing needs a cursor and nothing starves, including a
wiki added to the roster this morning.

The budget is wall-clock, not a number of wikis. What a run can get through
depends on the wikis it drew -- enwiki's sweep is not aawiki's -- on how the
replicas feel, and on what else is running; a count tuned for a good hour
overruns a bad one, and one tuned for a bad hour wastes a good one. A deadline
self-tunes to whatever capacity exists and can never spill into the next tick,
which matters because these lanes share the replicas with each other and the
database with two dozen other jobs.

The selected wikis are then reordered by replica section, so that a pass holding
one connection per instance does its wikis together rather than reopening. The
selection stays fair because it happens first: the reorder only decides the
order of wikis the run had already committed to.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func

from backend import db, wiki_replica
from backend.models import WikiLaneState, WikiProject, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

USERSCRIPT_LANE = "userscript"
GADGET_LANE = "gadget"

# How many due wikis a run is willing to consider. Not how many it will cover
# -- the budget decides that -- only how large a slice of the queue it reads and
# reorders in one go. Large enough that a fast run is never held back by it,
# small enough that the ordering query stays a bounded indexed read.
SELECTION: int = 250


@dataclass(frozen=True)
class Cadence:
    """How often a lane revisits a wiki, and how far that can move.

    The bounds belong to the lane and the value between them belongs to the
    wiki. A gadget inventory is one request and can afford to ask often; a
    user-script sweep is thousands and cannot. What neither can know in advance
    is which wikis are worth asking often, which is what `settle` learns.
    """

    #: Where a wiki starts before anything is known about it.
    initial: int
    #: The fastest a wiki is ever revisited, however busy it turns out to be.
    fastest: int
    #: The slowest an open wiki falls back to when it keeps reporting no change.
    slowest: int
    #: The slowest a closed wiki falls back to. Closed wikis still have to be
    #: discovered once, and after that they are the cheapest rows in the queue
    #: to leave alone: their scripts cannot change, because nobody can edit them.
    slowest_closed: int


CADENCES: dict[str, Cadence] = {
    # One request per wiki for the whole inventory, so this lane is cheap enough
    # to ask daily and its slow end is measured in weeks rather than months.
    GADGET_LANE: Cadence(initial=86_400, fastest=21_600, slowest=1_209_600, slowest_closed=7_776_000),
    # Thousands of requests for a first sweep and a recent-changes window after
    # that. The fast end is hourly because that is what a busy wiki's watch
    # costs; the slow end is a month because a quiet wiki's is the same request
    # returning nothing.
    USERSCRIPT_LANE: Cadence(initial=21_600, fastest=3_600, slowest=2_592_000, slowest_closed=7_776_000),
}

# After a failure, how long before the wiki is offered again -- doubling per
# consecutive failure up to the cap. Independent of cadence, because a wiki that
# could not be read is not a wiki that changed how often it is worth reading.
BACKOFF_BASE: int = 1_800
BACKOFF_MAX: int = 604_800


class Budget:
    """How much wall-clock a run may still spend.

    Held rather than passed around as a deadline so the loop reads as a question
    about the run -- `while budget.remains()` -- and so tests can drive it with
    a clock instead of sleeping.
    """

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Start the clock. `clock` is monotonic so a host clock step cannot end a run early."""
        self._clock = clock
        self._seconds = max(0.0, float(seconds))
        self._started = clock()

    @property
    def seconds(self) -> float:
        """The allowance this run began with."""
        return self._seconds

    def spent(self) -> float:
        """How long the run has been going."""
        return self._clock() - self._started

    def left(self) -> float:
        """How much of the allowance is unspent, never below zero."""
        return max(0.0, self._seconds - self.spent())

    def remains(self) -> bool:
        """Whether there is any allowance left to start another wiki with.

        Checked before a wiki rather than after, so the last wiki a run starts
        is one it had time for. It may still overrun -- nothing here interrupts
        a wiki mid-sweep, because a half-covered wiki is worse than a late run
        -- but it will not start a wiki with nothing left.
        """
        return self.left() > 0


@dataclass(frozen=True)
class Due:
    """One wiki a run has committed to covering, with what it takes to reach it."""

    wiki: str
    dbname: str
    section: str
    closed: bool
    #: When it was owed a turn. Kept so a run can report how far behind it is,
    #: which is the number that says whether the schedule is keeping up.
    due_at: datetime


@dataclass(frozen=True)
class Outcome:
    """What covering one wiki produced, as the schedule needs to hear it.

    Three facts rather than three arguments because they are one answer, and
    because a call site reading `Outcome(error=...)` cannot accidentally pass a
    failure as a change the way three positional booleans can.
    """

    #: Whether the pass found anything new. The one bit the cadence learns from.
    changed: bool = False
    #: Whether the wiki is closed, which sets how slow it is allowed to get.
    closed: bool = False
    #: Empty on success. Anything else is a failure and schedules by backoff.
    error: str = ""


def _cadence(lane: str) -> Cadence:
    return CADENCES.get(lane, CADENCES[USERSCRIPT_LANE])


def _by_section(entries: Sequence[Due]) -> tuple[Due, ...]:
    """Reorder a committed selection so wikis on one replica instance run together.

    Stable, so within a section the wikis stay in the order the queue chose. The
    only thing this changes is how many times a pooled pass opens a connection:
    869 wikis share one instance, and interleaving them with other sections
    would reopen it for each run of them.
    """
    return tuple(sorted(entries, key=lambda entry: entry.section))


def due(lane: str, *, now: datetime | None = None, limit: int = SELECTION) -> tuple[Due, ...]:
    """Read the wikis this lane owes a turn, most overdue first, grouped by section.

    A wiki with no state row for this lane has never been covered and is due
    immediately -- which is what makes adding a wiki to the registry enough to
    get it into the census, with nothing to backfill and no separate first run.
    """
    moment = now or utcnow()
    with db.session_scope() as session:
        # Naive UTC on both engines, and the epoch stands in for "never covered"
        # so that a wiki with no row sorts ahead of every wiki that has one.
        never = WikiProject.first_seen_at
        ordering = func.coalesce(WikiLaneState.next_due_at, never)
        rows = (
            session.query(WikiProject, ordering)
            .outerjoin(
                WikiLaneState,
                (WikiLaneState.wiki == WikiProject.wiki) & (WikiLaneState.lane == lane),
            )
            .filter(WikiProject.retired_at.is_(None), ordering <= moment)
            .order_by(ordering, WikiProject.wiki)
            .limit(max(1, limit))
            .all()
        )
        entries = tuple(
            Due(
                wiki=project.wiki,
                dbname=project.dbname,
                section=project.section,
                closed=bool(project.closed),
                due_at=due_at,
            )
            for project, due_at in rows
        )
    return _by_section(entries)


def named(wikis: Sequence[str], *, now: datetime | None = None) -> tuple[Due, ...]:
    """Turn a hand-written list of wiki hosts into a selection, for an override.

    An operator naming wikis on the command line is saying "cover these, now",
    so they arrive already due and in the order given. They carry no address,
    which is the honest answer -- nobody types a replica section -- and the
    resolver falls back to asking `meta_p` for exactly those wikis.
    """
    moment = now or utcnow()
    return tuple(Due(wiki=wiki, dbname="", section="", closed=False, due_at=moment) for wiki in wikis)


def addresses(entries: Sequence[Due]) -> dict[str, wiki_replica.Address]:
    """Hand the replica what the queue already knows about reaching each wiki."""
    return {
        entry.wiki: wiki_replica.Address(dbname=entry.dbname, section=entry.section)
        for entry in entries
        if entry.dbname
    }


def _state(session, wiki: str, lane: str) -> WikiLaneState:  # noqa: ANN001 - Session, deferred import
    row = session.query(WikiLaneState).filter(WikiLaneState.wiki == wiki, WikiLaneState.lane == lane).one_or_none()
    if row is None:
        # Every counter is set here rather than left to the column defaults,
        # which SQLAlchemy applies when the row is inserted and not when the
        # object is made. This function's whole purpose is to hand back a row
        # its caller then reads and increments, and it is called before any
        # flush -- so a column default would be `None` at exactly the moment it
        # is used.
        row = WikiLaneState(
            wiki=wiki,
            lane=lane,
            cadence_seconds=_cadence(lane).initial,
            next_due_at=utcnow(),
            consecutive_failures=0,
            runs=0,
        )
        session.add(row)
    return row


def start(wiki: str, lane: str, *, now: datetime | None = None) -> None:
    """Record that a run has begun covering this wiki.

    Written before the work rather than after it so that a run killed mid-wiki
    -- an out-of-memory sweep, a job guard's timeout -- still leaves evidence of
    which wiki it was on. Without it the only trace of the wiki that killed a
    job is the absence of a success, which every wiki the run never reached also
    has.
    """
    with db.session_scope() as session:
        _state(session, wiki, lane).last_started_at = now or utcnow()


def _tune(cadence: Cadence, current: int, *, changed: bool, closed: bool) -> int:
    """Move a wiki's interval toward how often it turns out to be worth asking.

    Halving on change and doubling on quiet, rather than any finer rule, because
    the input is one bit and the output only has to be roughly right: a wiki
    that is edited daily converges to the fast end within a week of runs, and one
    that has been quiet for years drifts to the slow end and stays there. Both
    directions are bounded, so no amount of either can take a wiki out of the
    queue or pin it to the top of it.
    """
    slowest = cadence.slowest_closed if closed else cadence.slowest
    if changed:
        return max(cadence.fastest, current // 2)
    return min(slowest, max(current * 2, cadence.fastest))


def settle(wiki: str, lane: str, outcome: Outcome, *, now: datetime | None = None) -> datetime:
    """Record how covering this wiki went, and say when it is next due.

    A success tunes the cadence and schedules by it. A failure leaves the
    cadence alone and schedules by backoff, so a replica having a bad afternoon
    costs a wiki some turns rather than its place in the rotation.
    """
    moment = now or utcnow()
    cadence = _cadence(lane)
    with db.session_scope() as session:
        row = _state(session, wiki, lane)
        row.runs += 1
        row.last_error = outcome.error or None
        if outcome.error:
            row.consecutive_failures += 1
            delay = min(BACKOFF_MAX, BACKOFF_BASE * 2 ** (row.consecutive_failures - 1))
        else:
            row.consecutive_failures = 0
            row.last_success_at = moment
            row.cadence_seconds = _tune(
                cadence,
                row.cadence_seconds or cadence.initial,
                changed=outcome.changed,
                closed=outcome.closed,
            )
            delay = row.cadence_seconds
        row.next_due_at = moment + timedelta(seconds=delay)
        return row.next_due_at


def backlog(lane: str, *, now: datetime | None = None) -> int:
    """How many wikis this lane owes a turn right now.

    The number that says whether the schedule is keeping up. A backlog that
    stays flat means the budget matches the work; one that grows every tick
    means it does not, and that is a decision about the budget rather than
    something the queue can fix by itself.
    """
    moment = now or utcnow()
    with db.session_scope() as session:
        ordering = func.coalesce(WikiLaneState.next_due_at, WikiProject.first_seen_at)
        return (
            session.query(func.count())
            .select_from(WikiProject)
            .outerjoin(
                WikiLaneState,
                (WikiLaneState.wiki == WikiProject.wiki) & (WikiLaneState.lane == lane),
            )
            .filter(WikiProject.retired_at.is_(None), ordering <= moment)
            .scalar()
            or 0
        )
