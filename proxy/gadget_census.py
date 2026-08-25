# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint for the gadget census."""

import os
import sys

from backend import gadget_creation_dates, gadget_inventory, gadget_toolinfo, job_runner
from backend.wikimedia_delivery import WikimediaClient

DEFAULT_WIKIS = "fr.wikipedia.org,meta.wikimedia.org"


def _wikis() -> list[str]:
    """List the wikis this run should cover, in order, from the environment."""
    raw = os.environ.get("GADGET_WIKIS", DEFAULT_WIKIS)
    return [wiki.strip() for wiki in raw.split(",") if wiki.strip()]


def main() -> int:
    """Read each wiki's gadget definitions, then rebuild its catalogue entries.

    One request per wiki. `MediaWiki:Gadgets-definition` is the entire
    inventory, so where the user-script census costs thousands of requests and
    is asked for explicitly, this can simply run on a schedule.

    Creation dates are stamped between the two passes, so a gadget dated for the
    first time publishes that date on the same tick rather than the next one.

    The catalogue pass follows every read, including one that changed nothing
    and one that failed. It talks to no wiki -- it rebuilds records from what
    the inventory stored -- so it costs seconds, and running it unconditionally
    means a change to what this codebase considers a tool takes effect on the
    next tick rather than waiting for a wiki to edit its definitions.
    """

    def body() -> None:
        client = WikimediaClient()
        for wiki in _wikis():
            read = gadget_inventory.ingest(client.request, wiki)
            sys.stdout.write(
                "gadget-inventory: "
                f"wiki={read['wiki']} read={'yes' if read['read'] else 'no'} "
                f"reason={read['reason']} "
                f"declared={read['declared']} added={read['added']} "
                f"updated={read['updated']} folded={read['folded']} "
                f"retired={read['retired']}\n",
            )
            stamped = gadget_creation_dates.backfill([wiki])
            sys.stdout.write(
                "gadget-creation-dates: "
                f"wiki={wiki} replica={'yes' if stamped else 'no'} "
                f"stamped={stamped.get(wiki, 0)}\n",
            )
            catalogued = gadget_toolinfo.synchronize(wiki)
            sys.stdout.write(
                "gadget-catalogue: "
                f"wiki={catalogued['wiki']} declared={catalogued['declared']} "
                f"written={catalogued['written']} unchanged={catalogued['unchanged']} "
                f"hidden={catalogued['hidden']} unnamed={catalogued['unnamed']} "
                f"duplicate={catalogued['duplicate']} conflicted={catalogued['conflicted']} "
                f"retired={catalogued['retired']}\n",
            )

    return job_runner.run_job("gadget-census", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
