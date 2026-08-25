# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled rebuild of the catalog statistics snapshot.

/statistics serves one precomputed document. Before this job existed the
rebuild happened inside whichever request first found the cached copy past
`SNAPSHOT_MAX_AGE`, and the only thing that refreshed it out of band ran every
six hours -- so a fifteen-minute freshness window meant nearly every visitor
paid for a full pass over the catalog, on a pod capped at half a CPU. Running
here, more often than that window, moves the cost off the request path.
"""

from __future__ import annotations

import sys

from backend import catalog_statistics, job_runner


def main(argv: list[str] | None = None) -> int:
    """Jobs-framework entrypoint: rebuild and store the statistics snapshot."""
    if argv:
        sys.stderr.write("statistics-refresh: takes no arguments\n")
        return 2
    job_runner.configure()
    # Not job_runner's own lock: catalog_statistics.refresh() already
    # serializes on the lock the web workers respect, and a second lock would
    # only add a way for the two to disagree. Retrying a disconnect is safe
    # because rebuilding is a pure read plus one idempotent write.
    return job_runner.run_job(
        "statistics-refresh",
        catalog_statistics.refresh,
        retry_on_disconnect=True,
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
