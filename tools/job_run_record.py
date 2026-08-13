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

from backend import DEFAULT_DB_URL, db
from backend.models import JobRun

# Enough history for the page to show a trend without unbounded growth. The
# minute-scheduled drain alone would otherwise add ~1,400 rows a day.
KEEP_RUNS_PER_JOB = 50


def _moment(value: str) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC).replace(tzinfo=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--started", required=True, help="unix seconds")
    parser.add_argument("--finished", required=True, help="unix seconds")
    parser.add_argument("--exit-code", required=True, type=int)
    args = parser.parse_args(argv)

    started = _moment(args.started)
    finished = _moment(args.finished)
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    with db.session_scope() as session:
        session.add(
            JobRun(
                job_name=args.job_name[:64],
                started_at=started,
                finished_at=finished,
                duration_seconds=max(0, int((finished - started).total_seconds())),
                exit_code=args.exit_code,
                succeeded=args.exit_code == 0,
            )
        )
        session.flush()
        keep = [
            row.id
            for row in session.query(JobRun)
            .filter(JobRun.job_name == args.job_name[:64])
            .order_by(JobRun.started_at.desc(), JobRun.id.desc())
            .limit(KEEP_RUNS_PER_JOB)
        ]
        session.query(JobRun).filter(
            JobRun.job_name == args.job_name[:64],
            JobRun.id.notin_(keep or [-1]),
        ).delete(synchronize_session=False)
    return 0


if __name__ == "__main__":  # pragma: no cover - invoked by tools/job_guard.sh
    raise SystemExit(main())
