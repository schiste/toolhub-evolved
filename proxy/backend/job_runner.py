# SPDX-License-Identifier: GPL-3.0-or-later
"""One entrypoint scaffold for every scheduled job.

Each job repeated the same preamble — resolve the database URL, create the
schema, optionally take the shared advisory lock, print a summary, choose an
exit code. Copying six lines is cheap; the copies diverging is not, and they
had: two spellings of the environment lookup with different empty-string
behaviour, four summary formats, and three exit-code policies feeding a
circuit breaker that acts on them (see backend.job_contract).

The lock convention is preserved exactly: a job that cannot take it prints
``{"locked": true}`` and exits zero, because losing a race with the job
already doing the work is a successful no-op, not a failure. A caller that
would rather queue than skip can ask for a bounded wait first; giving up is
still what happens when the wait runs out.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import DBAPIError

from backend import DEFAULT_DB_URL, db, job_contract

if TYPE_CHECKING:
    from collections.abc import Callable

LOCK_PREFIX = "toolhub-evolved:"


def database_url() -> str:
    """Resolve the configured database URL, falling back when it is unset.

    ``os.environ.get(...) or DEFAULT`` rather than ``os.getenv(name, DEFAULT)``
    so a set-but-empty variable falls back instead of reaching SQLAlchemy as an
    unparseable URL. Toolforge only injects the tool environment into
    webservice and job pods, so an entrypoint run anywhere else silently uses
    the local SQLite default; keeping one spelling keeps that behaviour uniform.
    """
    return os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL


def configure() -> None:
    """Prepare the shared database exactly as run_job() does.

    For the few entrypoints whose flow genuinely differs — a lock result folded
    into their own summary, or a real sweep-incomplete exit code — this shares
    the part that must not vary without forcing the rest into a shape that does
    not fit them.
    """
    db.configure(database_url())
    db.init_schema()


def _run_once(
    name: str,
    body: Callable[[], Any],
    *,
    lock: bool,
    lock_wait_seconds: int,
) -> int:
    """Take the lock if asked, run the body, print the summary, choose the code."""
    if lock:
        with db.advisory_lock(f"{LOCK_PREFIX}{name}", timeout_seconds=lock_wait_seconds) as acquired:
            if not acquired:
                sys.stdout.write(json.dumps({"locked": True}, sort_keys=True) + "\n")
                return job_contract.EXIT_OK
            summary = body()
    else:
        summary = body()
    if summary is not None:
        sys.stdout.write(f"{name}: " + json.dumps(summary, sort_keys=True) + "\n")
    return job_contract.EXIT_OK


def run_job(
    name: str,
    body: Callable[[], Any],
    *,
    lock: bool = False,
    lock_wait_seconds: int = 0,
    retry_on_disconnect: bool = False,
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
    """
    configure()
    try:
        return _run_once(name, body, lock=lock, lock_wait_seconds=lock_wait_seconds)
    except DBAPIError as exc:
        if not (retry_on_disconnect and exc.connection_invalidated):
            raise
        # Every pooled connection to a server that closed one is suspect, so
        # the retry starts from an empty pool rather than the next dead checkout.
        sys.stderr.write(f"{name}: database connection lost mid-run; retrying once\n")
    db.engine().dispose()
    return _run_once(name, body, lock=lock, lock_wait_seconds=lock_wait_seconds)
