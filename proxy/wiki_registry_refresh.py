# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint for the wiki registry refresh."""

import sys

from backend import job_runner, wiki_registry


def main() -> int:
    """Copy `meta_p`'s roster of readable wikis into the local registry.

    One connection and one read of a thousand-row table, weekly. That cadence
    is set by what the answer describes -- wikis are created, renamed and closed
    a few times a year -- and not by what needs it: the censuses read this table
    every hour, and having them each ask the replicas the same question instead
    would cost a `meta_p` connection per lane per tick to relearn something that
    had not changed.

    A run that could not reach a replica reports `read=0` and is not a failure.
    The registry it did not manage to update is the registry it already had,
    which names every wiki correctly until one is created; a job that failed
    here would take the census's schedule down with it for no better outcome.
    """

    def body() -> None:
        summary = wiki_registry.refresh()
        reason = summary["reason"]
        sys.stdout.write(
            "wiki-registry: "
            f"read={summary['read']} added={summary['added']} "
            f"updated={summary['updated']} retired={summary['retired']}"
            # Only when there was one. On the ordinary run there is nothing to
            # say, and a field that is almost always empty trains the reader to
            # skip the line it appears on.
            f"{f' reason={reason}' if reason else ''}\n",
        )

    return job_runner.run_job("wiki-registry", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
