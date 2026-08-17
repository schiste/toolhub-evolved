# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish executed background-job runs so /workers can report them.

A scheduled job records one row per run, through tools/job_guard.sh. A
continuous job has no run boundary to record, so it publishes a heartbeat into
the same table instead. The question the page exists to answer -- when did this
job last actually do something? -- has the same shape either way, and silence
still reads as stalled rather than as an absent job.

Publishing a run is observability: it must never be able to fail a job that
worked, so every caller treats it as best effort.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend import db
from backend.models import JobRun

if TYPE_CHECKING:
    from datetime import datetime

# Enough history for the page to show a trend without unbounded growth. The
# minute-scheduled drain alone would otherwise add ~1,400 rows a day.
KEEP_RUNS_PER_JOB = 50


def record(job_name: str, started: datetime, finished: datetime, exit_code: int) -> None:
    """Store one executed run and trim this job's history to KEEP_RUNS_PER_JOB."""
    name = job_name[:64]
    with db.session_scope() as session:
        session.add(
            JobRun(
                job_name=name,
                started_at=started,
                finished_at=finished,
                duration_seconds=max(0, int((finished - started).total_seconds())),
                exit_code=exit_code,
                succeeded=exit_code == 0,
            )
        )
        session.flush()
        keep = [
            row.id
            for row in session.query(JobRun)
            .filter(JobRun.job_name == name)
            .order_by(JobRun.started_at.desc(), JobRun.id.desc())
            .limit(KEEP_RUNS_PER_JOB)
        ]
        session.query(JobRun).filter(JobRun.job_name == name, JobRun.id.notin_(keep or [-1])).delete(
            synchronize_session=False
        )
