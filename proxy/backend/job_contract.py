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
