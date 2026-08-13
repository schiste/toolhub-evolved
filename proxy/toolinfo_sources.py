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

    return job_runner.run_job("toolinfo-source-index", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
