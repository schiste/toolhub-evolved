# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint that names the tools recent list revisions changed."""

import os
import sys

from backend import catalog_read, job_runner, list_revisions

RECENT_PATH = "/api/recent/"


def _limit() -> int:
    """Cap how many revisions one run may resolve, from the environment."""
    try:
        return max(1, int(os.environ.get("LIST_REVISION_LIMIT", "")))
    except ValueError:
        return list_revisions.DEFAULT_INGEST_LIMIT


def main() -> int:
    """Read the diff of each recent list revision the replica has not resolved.

    The recent-changes feed names no tool: "Added tool to list" is the whole
    comment upstream sends.  The name is only in the revision diff, one request
    per revision, which is why this runs here rather than while a page renders.

    Work is found by anti-join against what is already stored, so a run costs
    requests only for revisions that appeared since the last one.  On a quiet
    day that is zero.
    """

    def body() -> None:
        counts = list_revisions.ingest(catalog_read.replica_rows(RECENT_PATH), limit=_limit())
        sys.stdout.write(
            "list-revision-sync: "
            f"pending={counts['pending']} named={counts['named']} "
            f"uneventful={counts['uneventful']} unreadable={counts['unreadable']}\n",
        )

    return job_runner.run_job("list-revision-sync", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
