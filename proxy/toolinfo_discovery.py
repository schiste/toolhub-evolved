# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint for automated toolinfo.json discovery."""

import os
import sys

from backend import job_runner, toolinfo_discovery


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def main() -> int:
    """Refresh cached toolinfo discovery rows for official Toolhub tools."""
    limit = _int_env("TOOLINFO_DISCOVERY_LIMIT", 100)

    def body() -> None:
        summary = toolinfo_discovery.refresh_known_discoveries(limit=limit)
        sys.stdout.write(
            "toolinfo-discovery: "
            f"limit={limit} "
            f"refreshed={summary['refreshed']} "
            f"seeded={summary['seeded']} "
            f"found={summary['found']} "
            f"missing={summary['missing']} "
            f"errors={summary['errors']} "
            f"skipped={summary['skipped']}\n"
        )

    return job_runner.run_job("toolinfo-discovery", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
