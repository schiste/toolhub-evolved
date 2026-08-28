# SPDX-License-Identifier: GPL-3.0-or-later
"""Report workers that have stopped reporting, because nothing else can.

`workers.snapshot` already classifies every declared job against its own
schedule, and `_status` calls a stalled worker the state that "must be
impossible to miss". It was missed anyway: the classification was only ever
rendered on /workers, so noticing it required a human to open the page.

The gap it leaves is not theoretical, and not rare. Three times now a job has
died on every single tick while every automatic surface reported nothing:

* `catalog-validation`, from 2026-08-25 19:06, OOM-killed for a day.
* `inference-enrichment`, from 2026-08-27 13:41, OOM-killed for 16 hours.
* `crawler`, from 2026-08-03, breaker-tripped for ten days.

Each was invisible for the same reason. A job dies in one of three ways that
produce no failure mail: SIGKILL, which skips `job_guard.sh`'s exit trap so no
run is ever recorded; the guard's overlap skip, which exits 0 by design; and
the guard's breaker, which also exits 0. `emails: onfailure` fires on a
non-zero exit, and none of those three produce one. The job's own silence is
the only evidence that exists, so something has to read it on a schedule.

That is all this module does: read the classification that already exists and
turn it into a non-zero exit, which is the one signal Toolforge will mail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend import workers

if TYPE_CHECKING:
    from collections.abc import Sequence

#: States that wake someone. `late` is included deliberately even though
#: `workers` notes that schedules slip for ordinary reasons -- the operator
#: chose coverage over quiet, and a slip that resolves itself costs one mail
#: while a slip that does not is the early edge of a stall.
ALARMING = (workers.STATUS_STALLED, workers.STATUS_FAILING, workers.STATUS_LATE)

#: Reported in the summary but never alarmed on. `unknown` means the job has
#: never recorded a run at all, which reads identically for a job deployed
#: minutes ago, a job on a freshly restored database, and a job that has been
#: broken since birth. Alarming on it would fire for all 32 jobs at once after
#: a restore. The honest cost is stated rather than hidden: a job that has
#: never once succeeded stays quiet here, and only /workers will show it.
QUIET = (workers.STATUS_UNKNOWN,)


def _entry(worker: dict[str, Any]) -> dict[str, Any]:
    """Reduce one worker to what a failure mail needs to act on it."""
    return {
        "name": worker["name"],
        "status": worker["status"],
        "lastRunAt": worker["lastRunAt"],
        "lastSuccessAt": worker["lastSuccessAt"],
        "minutesSinceLastRun": worker["minutesSinceLastRun"],
        "expectedIntervalMinutes": worker["expectedIntervalMinutes"],
        "lastRunExitCode": worker["lastRunExitCode"],
    }


def _by_status(entries: Sequence[dict[str, Any]], status: str) -> list[str]:
    return sorted(entry["name"] for entry in entries if entry["status"] == status)


def check(session: Any) -> dict[str, Any]:  # noqa: ANN401 - SQLAlchemy session
    """Classify every declared worker and say which ones warrant a mail.

    Returns the summary this job prints. `alarming` is what the caller turns
    into an exit code; everything else is there so the mail explains itself
    without needing the page open.
    """
    snapshot = workers.snapshot(session)
    all_workers = snapshot["workers"]
    alarming = [_entry(worker) for worker in all_workers if worker["status"] in ALARMING]
    quiet = [_entry(worker) for worker in all_workers if worker["status"] in QUIET]
    return {
        "checked": len(all_workers),
        "counts": snapshot["counts"],
        "alarming": sorted(alarming, key=lambda entry: (entry["status"], entry["name"])),
        # Named rather than counted: the whole point is that these are the
        # jobs no automatic signal will ever mention again.
        "neverRan": sorted(entry["name"] for entry in quiet),
        "stalled": _by_status(alarming, workers.STATUS_STALLED),
        "failing": _by_status(alarming, workers.STATUS_FAILING),
        "late": _by_status(alarming, workers.STATUS_LATE),
    }
