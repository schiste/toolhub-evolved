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
already doing the work is a successful no-op, not a failure.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any

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


def run_job(
    name: str,
    body: Callable[[], Any],
    *,
    lock: bool = False,
) -> int:
    """Run one job body with the shared database, lock, and exit conventions.

    ``body`` returns a mapping to be printed as this job's summary, or None
    when it has already written its own human-readable line.
    """
    configure()
    if lock:
        with db.advisory_lock(f"{LOCK_PREFIX}{name}") as acquired:
            if not acquired:
                sys.stdout.write(json.dumps({"locked": True}, sort_keys=True) + "\n")
                return job_contract.EXIT_OK
            summary = body()
    else:
        summary = body()
    if summary is not None:
        sys.stdout.write(f"{name}: " + json.dumps(summary, sort_keys=True) + "\n")
    return job_contract.EXIT_OK
