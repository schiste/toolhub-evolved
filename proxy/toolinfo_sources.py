# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint for official Toolhub crawler source indexing."""

import os
import sys

from backend import job_runner, toolinfo_sources


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def main() -> int:
    """Refresh official crawler source mappings in the local DB."""
    limit = _int_env("TOOLINFO_SOURCE_INDEX_LIMIT", 150)

    def body() -> None:
        summary = toolinfo_sources.index_official_crawler_sources(limit=limit)
        sys.stdout.write(
            "toolinfo-sources: "
            f"limit={limit} "
            f"registered={summary['registered']} "
            f"skipped={summary['skipped']} "
            f"fetched={summary['fetched']} "
            f"valid={summary['valid']} "
            f"invalid={summary['invalid']} "
            f"errors={summary['errors']} "
            f"items={summary['items']}\n"
        )

    # Mirrors a remote listing into local tables and re-decides each mapping
    # from what it just fetched, so a run the database rolled back for a lock
    # left nothing behind and a second attempt reaches the same state. It writes
    # tool_relationship_evidence, which six jobs contend on, and it is one of
    # the two that genuinely failed on errno 1205 rather than absorbing it.
    return job_runner.run_job(
        "toolinfo-source-index",
        body,
        retry_on_lock_timeout=job_runner.lock_retry_deadline_seconds("toolinfo-source-index"),
    )


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
