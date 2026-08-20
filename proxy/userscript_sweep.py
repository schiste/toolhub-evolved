# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint for the user-script census."""

import os
import sys

from backend import job_runner, userscript_sweep
from backend.wikimedia_delivery import WikimediaClient

DEFAULT_WIKIS = "fr.wikipedia.org"


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _wikis() -> list[str]:
    """List the wikis this run should cover, in order, from the environment."""
    raw = os.environ.get("USERSCRIPT_WIKIS", DEFAULT_WIKIS)
    return [wiki.strip() for wiki in raw.split(",") if wiki.strip()]


def main() -> int:
    """Sweep or watch each configured wiki's user-space script pages.

    A full sweep is thousands of requests and is not something to run hourly, so
    the schedule runs a watch and the sweep is asked for explicitly. The first
    run on a wiki has no cursor, and a watch with no cursor would learn only
    what changed since it started -- so a wiki with no completed sweep gets one
    whether or not this run asked for it.
    """
    full = os.environ.get("USERSCRIPT_SWEEP", "").strip().lower() in {"1", "true", "yes"}
    limit = _int_env("USERSCRIPT_LIMIT", 0)
    watch_limit = _int_env("USERSCRIPT_WATCH_LIMIT", userscript_sweep.WATCH_LIMIT) or userscript_sweep.WATCH_LIMIT

    def body() -> None:
        client = WikimediaClient()
        for wiki in _wikis():
            summary = userscript_sweep.run(
                client.request,
                wiki,
                full=full,
                limit=limit,
                watch_limit=watch_limit,
            )
            sys.stdout.write(
                "userscript-census: "
                f"wiki={summary['wiki']} mode={summary['mode']} "
                f"asked={summary['asked']} fetched={summary['fetched']} "
                f"written={summary['written']} skipped={summary['skipped']} "
                f"unreadable={summary['unreadable']}\n",
            )

    return job_runner.run_job("userscript-census", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
