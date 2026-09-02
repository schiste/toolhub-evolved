# SPDX-License-Identifier: GPL-3.0-or-later
"""One entrypoint scaffold for every scheduled job.

Each job repeated the same preamble — resolve the database URL, create the
schema, optionally take the shared advisory lock, print a summary, choose an
exit code. Copying six lines is cheap; the copies diverging is not, and they
had: two spellings of the environment lookup with different empty-string
behaviour, four summary formats, and three exit-code policies feeding a
circuit breaker that acts on them (see backend.job_contract).

A job that cannot take the lock prints ``{"locked": true}`` and returns
``job_contract.EXIT_SKIPPED``. It used to return ``EXIT_OK``, on the reasoning
that losing a race with the job already doing the work is a successful no-op.
That is true of the run and false of the record: the guard wrote a job_runs row
for it, so /workers reported a healthy job that had in fact done nothing for
eight hours. A skip is neither outcome, and now says so. A caller that would
rather queue than skip can ask for a bounded wait first; giving up is still
what happens when the wait runs out.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import sys
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import DBAPIError

from backend import DEFAULT_DB_URL, db, job_contract

if TYPE_CHECKING:
    from collections.abc import Callable

LOCK_PREFIX = "toolhub-evolved:"
# Held by a job that is queueing for the shared lock, for as long as it queues.
# The lock itself cannot express this: `GET_LOCK` hands the lock to whoever asks
# at the moment it frees, which is the job that asks most often, not the job
# that has been waiting longest. people-reconcile-incremental asks every minute
# and is unwilling to wait; people-identity-reconcile asks once an hour and
# waits two minutes for it, and on 2026-08-29 lost eight hours in a row. This is
# how the losing side gets to say it is there.
INTENT_SUFFIX = ":waiting"


def database_url() -> str:
    """Resolve the configured database URL, falling back when it is unset.

    ``os.environ.get(...) or DEFAULT`` rather than ``os.getenv(name, DEFAULT)``
    so a set-but-empty variable falls back instead of reaching SQLAlchemy as an
    unparseable URL. Toolforge only injects the tool environment into
    webservice and job pods, so an entrypoint run anywhere else silently uses
    the local SQLite default; keeping one spelling keeps that behaviour uniform.
    """
    return os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL


def configure(*, concurrency: int = 1) -> None:
    """Prepare the shared database exactly as run_job() does.

    For the few entrypoints whose flow genuinely differs — a lock result folded
    into their own summary, or a real sweep-incomplete exit code — this shares
    the part that must not vary without forcing the rest into a shape that does
    not fit them.

    ``concurrency`` is how many units of work the job runs at once. One is the
    truth for every job that does its work on the calling thread, which is all
    of them but projection_refresh; a job that grows a thread pool has to say
    so here too, or its threads contend for a pool sized for one of them.
    """
    db.configure(database_url(), concurrency=concurrency)
    db.init_schema()


def _skipped(**detail: int | None) -> int:
    """Report a run that never started, and say which lock turned it away.

    Eight consecutive skips are indistinguishable from each other without it,
    and the answer decides the fix: a once-a-minute job taking the lock briefly
    needs different work than one run holding it for twenty minutes. It is
    always the losing side that has to ask -- the holder has no reason to
    announce itself -- so the question is asked here, once, at the only moment
    the answer matters.
    """
    sys.stdout.write(json.dumps({"locked": True, **detail}, sort_keys=True) + "\n")
    return job_contract.EXIT_SKIPPED


def _publish(name: str, summary: object) -> None:
    """Print the run summary, and hand it to the guard if the guard asked for it.

    The process that knows what the run did cannot write the job_runs row: the
    guard writes that, afterwards, because only the guard can tell a child that
    finished from one that was killed without a word. So the summary is left
    where the guard said to leave it, in TOOLHUB_JOB_SUMMARY_FILE, and the guard
    reads it back once the child's fate is known. Purely additive: nothing here
    can fail a run that worked, and a job run outside the guard simply prints.
    """
    sys.stdout.write(f"{name}: " + json.dumps(summary, sort_keys=True) + "\n")
    handoff = os.environ.get("TOOLHUB_JOB_SUMMARY_FILE")
    if not handoff:
        return
    with contextlib.suppress(OSError, TypeError, ValueError):
        pathlib.Path(handoff).write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")


def _run_once(
    name: str,
    body: Callable[[], Any],
    *,
    lock: bool,
    lock_wait_seconds: int,
    before_lock: Callable[[], None] | None = None,
) -> int:
    """Take the lock if asked, run the body, print the summary, choose the code."""
    if before_lock is not None:
        before_lock()
    if not lock:
        summary = body()
        if summary is not None:
            _publish(name, summary)
        return job_contract.EXIT_OK

    lock_name = f"{LOCK_PREFIX}{name}"
    intent_name = f"{lock_name}{INTENT_SUFFIX}"
    # One budget covers both locks, so announcing intent cannot double the wait
    # a caller signed up for -- which has to stay well inside its job timeout.
    started = time.monotonic()
    with contextlib.ExitStack() as stack:
        if lock_wait_seconds > 0:
            # Willing to queue, so it queues visibly. Held for the whole run
            # rather than dropped once the lock is won: a second waiter would
            # otherwise wait out the run on the lock instead of on this, which
            # ends the same way, and releasing early is the only version of this
            # that can leave the flag set with nobody behind it.
            if not stack.enter_context(db.advisory_lock(intent_name, timeout_seconds=lock_wait_seconds)):
                return _skipped(queuedBehind=db.advisory_lock_holder(intent_name))
        elif (waiter := db.advisory_lock_holder(intent_name)) is not None:
            # Unwilling to wait, which is only affordable because another
            # attempt is a minute away -- so it can afford to give this one up.
            # Checked before the lock and not after losing it: the starvation is
            # not that the lock is busy, it is that a job asking every minute
            # takes it back in the instant it frees, before the job that has
            # been waiting since :43 is handed anything.
            return _skipped(yieldedTo=waiter)
        remaining = max(0, lock_wait_seconds - int(time.monotonic() - started))
        if not stack.enter_context(db.advisory_lock(lock_name, timeout_seconds=remaining)):
            return _skipped(heldBy=db.advisory_lock_holder(lock_name))
        summary = body()
    if summary is not None:
        _publish(name, summary)
    return job_contract.EXIT_OK


def _lock_retry_due(name: str, error: DBAPIError, budget_seconds: int, elapsed: float) -> bool:
    """Whether a run the database rolled back for a lock has time to try again.

    A retry costs about what the aborted attempt would have, so it is only
    offered while at least that much of the job's timeout is left. Past that
    the abort is reported as the failure it is: exit 1 mails, whereas a retry
    that runs past the timeout is a SIGKILL, and a kill is one of the three
    ways a job dies without saying anything at all.
    """
    if budget_seconds <= 0 or not db.is_transient_lock_error(error):
        return False
    if elapsed > budget_seconds:
        sys.stderr.write(f"{name}: lost a row lock {int(elapsed)}s in; too late in the run to retry\n")
        return False
    sys.stderr.write(f"{name}: lost a row lock {int(elapsed)}s in; retrying once\n")
    return True


def run_job(  # noqa: PLR0913 - one keyword per job-shape difference, which is the point of the scaffold
    name: str,
    body: Callable[[], Any],
    *,
    lock: bool = False,
    lock_wait_seconds: int = 0,
    retry_on_disconnect: bool = False,
    retry_on_lock_timeout: int = 0,
    before_lock: Callable[[], None] | None = None,
) -> int:
    """Run one job body with the shared database, lock, and exit conventions.

    ``body`` returns a mapping to be printed as this job's summary, or None
    when it has already written its own human-readable line.

    ``lock_wait_seconds`` queues for the lock instead of giving up the instant
    someone else holds it, for the jobs whose scheduling gap is shorter than
    the runs they contend with -- see people_reconcile. It must stay well
    inside the caller's own job timeout: waiting past that is a kill, and a
    kill is strictly worse than the skip it replaced. Waiting adds no
    concurrency, so it does not reintroduce the deadlocks the lock prevents.

    ``before_lock`` runs once the database is configured but before the lock is
    taken, for the part of a job that provably needs neither. people_reconcile's
    remote phase is two minutes of Wikimedia round trips over a batch it has
    already read and closed its session on, and holding the shared lock through
    them was two minutes of a hold four jobs contend for, in a pass that already
    finishes within a hundred seconds of its own timeout. It runs before the
    lock rather than inside it, so a run that then loses the lock has spent that
    work for nothing -- worth it only where the work is bounded and the loss is
    rare, which is why this is opt-in per caller rather than a phase of the
    scaffold.

    ``retry_on_disconnect`` runs the body a second time when ToolsDB closes the
    connection underneath it. ``pool_pre_ping`` only proves a connection is
    alive at checkout, so a pass long enough for the server to drop it mid-run
    still dies on its next statement; the open transaction rolls back whole and
    the run is simply lost. people-identity-reconcile lost 01:43, 02:43 and
    03:43 on 2026-08-18 that way, each leaving its guard lock to be reclaimed
    an hour later. It is opt-in because a second run is only safe for a body
    that is idempotent -- a job that has already sent mail or called a remote
    write must not repeat it.

    The retry re-enters through the lock rather than resuming inside it. A
    dropped connection releases the locks it held, so continuing would run
    unserialized against whoever acquired it next; re-acquiring either wins the
    lock again or reports the skip that losing it has always meant.

    ``retry_on_lock_timeout`` is the same bargain for the other way ToolsDB
    ends a long pass: an InnoDB lock wait that expires takes the whole
    transaction with it, and MySQL's own advice for errno 1205 is to run it
    again. It is a number of seconds, not a flag, because the retry is only
    worth offering while the timeout has room for it -- see `_lock_retry_due`.
    Like the disconnect retry it is opt-in and happens once: a body that lost
    the same race twice is contending with something a third attempt will not
    outlast, and saying so is more useful than a third.
    """
    configure()
    # Only the lock budget needs the clock, and reading it unconditionally would
    # make every other caller pay for a feature it did not ask for.
    started = time.monotonic() if retry_on_lock_timeout else 0.0
    try:
        return _run_once(name, body, lock=lock, lock_wait_seconds=lock_wait_seconds, before_lock=before_lock)
    except DBAPIError as exc:
        if retry_on_disconnect and exc.connection_invalidated:
            # Every pooled connection to a server that closed one is suspect, so
            # the retry starts from an empty pool rather than the next dead checkout.
            sys.stderr.write(f"{name}: database connection lost mid-run; retrying once\n")
            db.engine().dispose()
        elif not _lock_retry_due(name, exc, retry_on_lock_timeout, time.monotonic() - started):
            raise
    return _run_once(name, body, lock=lock, lock_wait_seconds=lock_wait_seconds, before_lock=before_lock)
