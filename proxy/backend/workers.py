# SPDX-License-Identifier: GPL-3.0-or-later
"""Public status of the background workers that keep Evolved's data current."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from backend import job_catalog
from backend.models import JobRun, utcnow

if TYPE_CHECKING:
    from datetime import datetime

# A schedule slips for ordinary reasons — contention, a slow upstream, a
# restart — so lateness alone is not a fault. Silence for many periods is:
# that is what a leaked lock or a tripped breaker looks like from outside,
# and what went unnoticed for ten days because nobody was looking.
LATE_PERIODS = 3
STALLED_PERIODS = 10
RECENT_RUNS = 10

STATUS_HEALTHY = "healthy"
STATUS_FAILING = "failing"
STATUS_LATE = "late"
STATUS_STALLED = "stalled"
STATUS_UNKNOWN = "unknown"


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") + "Z" if value else ""


def _status(job: job_catalog.ScheduledJob, last: JobRun | None, minutes_since: float | None) -> str:
    """Classify one worker from its own schedule, never a global threshold.

    A minute-scheduled drain and a weekly audit are both healthy at wildly
    different silences, so every verdict is relative to that job's period.
    """
    if last is None or minutes_since is None:
        return STATUS_UNKNOWN
    period = job.expected_interval_minutes
    if period <= 0:
        return STATUS_FAILING if not last.succeeded else STATUS_UNKNOWN
    if minutes_since >= period * STALLED_PERIODS:
        # Nothing has executed in long enough that the schedule is not being
        # honoured at all. This is the state that must be impossible to miss.
        return STATUS_STALLED
    if not last.succeeded:
        return STATUS_FAILING
    if minutes_since >= period * LATE_PERIODS:
        return STATUS_LATE
    return STATUS_HEALTHY


def snapshot(session: Any) -> dict[str, Any]:  # noqa: ANN401 - SQLAlchemy session
    """Return every declared worker with its most recent executed runs."""
    now = utcnow()
    jobs = job_catalog.load()
    names = [job.name for job in jobs]
    latest: dict[str, JobRun] = {}
    history: dict[str, list[JobRun]] = {}
    if names:
        rows = session.execute(
            select(JobRun).where(JobRun.job_name.in_(names)).order_by(JobRun.started_at.desc(), JobRun.id.desc())
        ).scalars()
        for row in rows:
            entries = history.setdefault(row.job_name, [])
            if len(entries) < RECENT_RUNS:
                entries.append(row)
            latest.setdefault(row.job_name, row)
    last_success = dict(
        session.execute(
            select(JobRun.job_name, func.max(JobRun.started_at))
            .where(JobRun.job_name.in_(names or [""]), JobRun.succeeded.is_(True))
            .group_by(JobRun.job_name)
        ).all()
    )

    workers = []
    for job in jobs:
        last = latest.get(job.name)
        minutes_since = (now - last.started_at).total_seconds() / 60 if last else None
        workers.append(
            {
                "name": job.name,
                "description": job.description,
                "schedule": job.schedule,
                "expectedIntervalMinutes": job.expected_interval_minutes,
                "timeoutSeconds": job.timeout_seconds,
                "status": _status(job, last, minutes_since),
                "lastRunAt": _iso(last.started_at if last else None),
                "lastRunSucceeded": bool(last.succeeded) if last else None,
                "lastRunDurationSeconds": last.duration_seconds if last else None,
                "lastRunExitCode": last.exit_code if last else None,
                "lastSuccessAt": _iso(last_success.get(job.name)),
                "minutesSinceLastRun": round(minutes_since) if minutes_since is not None else None,
                "recentRuns": [
                    {
                        "startedAt": _iso(row.started_at),
                        "durationSeconds": row.duration_seconds,
                        "succeeded": bool(row.succeeded),
                        "exitCode": row.exit_code,
                    }
                    for row in history.get(job.name, ())
                ],
            }
        )
    counts: dict[str, int] = {}
    for worker in workers:
        counts[worker["status"]] = counts.get(worker["status"], 0) + 1
    return {
        "generatedAt": _iso(now),
        "workers": workers,
        "counts": dict(sorted(counts.items())),
        "definitions": {
            "recorded": "Only runs that executed are recorded; a skipped overlap is routine and is not a run.",
            "late": f"No run for {LATE_PERIODS} or more of this job's own scheduled periods.",
            "stalled": f"No run for {STALLED_PERIODS} or more periods, so the schedule is not being honoured.",
            "unknown": "No run has been recorded yet, which is expected for a newly added worker.",
        },
    }
