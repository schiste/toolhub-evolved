# SPDX-License-Identifier: GPL-3.0-or-later
"""What a scheduled job's exit code means to tools/job_guard.sh.

The guard counts consecutive non-zero exits and trips a circuit breaker, so
an exit code is not a report — it is an instruction to keep running this job
or to stop running it. That makes one question load-bearing, and it had been
answered three different ways across the job entrypoints, none of them
deliberately:

    tool_assets.py        always 0, with a comment explaining why
    catalog_projection.py 1 whenever any single item errored
    crawl.py              1 whenever any single registered URL errored

The last one is not hypothetical. The crawler has exactly one registered URL,
so one unreachable feed made the whole job exit non-zero; three hourly runs
of that in a row tripped the breaker on 2026-08-03, and the job then ran zero
times until 2026-08-13 even though the URL had long recovered.

The contract:

**Exit non-zero when the sweep itself could not run or could not complete.
Per-item failures are durable observations, not job failures.**

A sweep that reached its sources, recorded three of them as unreachable, and
wrote that to the database did its job — the world was simply imperfect that
hour, and the failure is already visible as data. Retiring the job in that
case destroys the very reporting that would explain the outage. Infrastructure
faults (an unreachable database, a bad configuration, an unhandled error)
still raise or return non-zero, because those genuinely mean "do not keep
running this".

A job that wants the opposite for a specific reason may still return non-zero;
it just has to say why at the return, the way tool_assets.py already does.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_SWEEP_FAILED = 1

# A run that never started because someone else held the shared lock. Not a
# success and not a failure: nothing was attempted, so recording it either way
# is a lie. It had been reported as EXIT_OK, which meant tools/job_guard.sh
# wrote a job_runs row for it and backend.workers read that row as "this job
# ran and succeeded". people-identity-reconcile skipped eight hourly ticks in a
# row on 2026-08-29 while /workers showed a fresh successful run each hour --
# the fourth way a job can stop without anyone being told, after the SIGKILL,
# the overlap skip and the breaker that job_watchdog was built for.
#
# Non-zero so the guard can tell it apart from a real success, and handled by
# the guard rather than reaching Toolforge, which mails on any non-zero exit.
# The guard swallows it exactly like its own overlap skip: no run recorded, no
# effect on the breaker, and zero to the platform. Kept out of the 1-64 range
# a sweep might plausibly return, and out of 128+n, which means "killed by
# signal n".
EXIT_SKIPPED = 75
