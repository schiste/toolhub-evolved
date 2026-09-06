# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled rebuild of the catalog coverage snapshot.

The data-layer page serves one precomputed document, exactly as /statistics
does, and both call a rebuild stale past six hours. Statistics has a job of its
own every ten minutes; coverage had none. Its only refresh was one stage inside
`projection-refresh`, which runs every six hours -- so the refresh interval
equalled the staleness limit and left no margin at all. Any run that was late,
deferred, or failed put the snapshot past the limit, and the next visitor
rebuilt the whole catalogue inside their own request: measured at 11.5s median
and 14.9s worst across nine runs, on a pod capped at half a CPU.

That is the failure `statistics-refresh` was created to end, described in its
own module and in jobs.yaml, one page over. This is the same job for the other
document, and it leaves `projection-refresh` free to keep its coverage stage as
the thing that publishes a fresh snapshot immediately after an identity pass
changes what coverage would say.
"""

from __future__ import annotations

import sys

from backend import catalog_coverage, job_runner


def main(argv: list[str] | None = None) -> int:
    """Jobs-framework entrypoint: rebuild and store the coverage snapshot."""
    if argv:
        sys.stderr.write("coverage-refresh: takes no arguments\n")
        return 2
    job_runner.configure()
    # Not job_runner's own lock, for the reason statistics_refresh gives:
    # catalog_coverage.refresh() already serializes on the advisory lock the
    # web workers respect, and a second lock would only add a way for the two
    # to disagree. Retrying a disconnect is safe because rebuilding is a pure
    # read plus one idempotent write.
    return job_runner.run_job(
        "coverage-refresh",
        catalog_coverage.refresh,
        retry_on_disconnect=True,
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
