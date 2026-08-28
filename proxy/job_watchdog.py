# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job that mails when a worker has gone quiet.

Runs **without** `tools/job_guard.sh`, which is deliberate and load-bearing.
The guard counts consecutive non-zero exits and disables the job at three, and
this job exits non-zero precisely when something is wrong elsewhere. Under the
guard, a stall lasting three ticks would silence the only thing reporting it --
the exact failure `job_contract` records for the crawler, which ran zero times
from 2026-08-03 to 2026-08-13 after a transient blip tripped its breaker. The
guard's other services are not needed either: there is no lock to hold for a
read-only query that finishes in well under a second, and no expensive work to
stop repeating.

`job_contract` asks a job returning non-zero for a reason other than "the sweep
could not run" to say why at the return, which is what `main` does below.
"""

from __future__ import annotations

import sys
from typing import Any

from backend import db, job_contract, job_runner, job_runs, job_watchdog
from backend.models import utcnow

JOB_NAME = "job-watchdog"


def main() -> int:
    started = utcnow()
    report: dict[str, Any] = {}

    def body() -> dict[str, Any]:
        nonlocal report
        with db.session_scope() as session:
            report = job_watchdog.check(session)
        return report

    job_runner.run_job(JOB_NAME, body)

    # Publish our own run, which `job_guard.sh` would otherwise have done. The
    # code recorded is the sweep's, not this process's: the sweep succeeded
    # whenever it read the table, and the non-zero exit below is a verdict
    # about other jobs rather than a fault in this one. Recording the verdict
    # here instead would make the watchdog permanently unhealthy on /workers
    # for as long as anything else was, and would hide its own death behind
    # somebody else's.
    try:
        job_runs.record(JOB_NAME, started, utcnow(), job_contract.EXIT_OK)
    except Exception as exc:  # noqa: BLE001 - observability must not fail the sweep
        sys.stderr.write(f"{JOB_NAME}: could not record run: {exc}\n")

    if not report.get("alarming"):
        return job_contract.EXIT_OK
    # Non-zero for a reason `job_contract` does not cover: the sweep ran fine.
    # This is the report itself. Toolforge mails on a non-zero exit and on
    # nothing else, so for a job whose entire output is "something else has
    # gone quiet", the exit code is the only channel that reaches a human.
    names = ", ".join(f"{entry['name']} ({entry['status']})" for entry in report["alarming"])
    sys.stderr.write(f"{JOB_NAME}: {len(report['alarming'])} worker(s) need attention: {names}\n")
    return job_contract.EXIT_SWEEP_FAILED


if __name__ == "__main__":
    sys.exit(main())
