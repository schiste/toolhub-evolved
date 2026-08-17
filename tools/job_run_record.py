# SPDX-License-Identifier: GPL-3.0-or-later
"""Record one executed scheduled-job run so /workers can report it.

Invoked by tools/job_guard.sh after the child command returns. The guard
calls this best-effort and discards its status: publishing a run is
observability, and it must never be able to fail a job that worked.

Only executed runs are recorded. Skipped overlaps are routine and would bury
the useful signal, and the question this exists to answer is the one nobody
could answer for ten days: when did this job last actually run?
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proxy"))

from backend import DEFAULT_DB_URL, db, job_runs

KEEP_RUNS_PER_JOB = job_runs.KEEP_RUNS_PER_JOB


def _moment(value: str) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC).replace(tzinfo=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--started", required=True, help="unix seconds")
    parser.add_argument("--finished", required=True, help="unix seconds")
    parser.add_argument("--exit-code", required=True, type=int)
    args = parser.parse_args(argv)

    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    job_runs.record(args.job_name, _moment(args.started), _moment(args.finished), args.exit_code)
    return 0


if __name__ == "__main__":  # pragma: no cover - invoked by tools/job_guard.sh
    raise SystemExit(main())
