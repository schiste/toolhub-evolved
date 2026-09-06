# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled read of each gadget's own code.

The gadget inference lane reads the description message, which is 83 characters
at the median and absent for 2,726 of 12,777 gadgets -- one sentence, and often
not even that. It answers `keywords` and `audiences` because those are what a
sentence can support; a tech stack or a set of interface languages cannot be
read from it, and asking anyway returns a guess wearing a reading's clothes.

Every gadget has code. This puts it where the lane can reach it.
"""

from __future__ import annotations

import os
import sys

from backend import gadget_source, job_runner


def main(argv: list[str] | None = None) -> int:
    """Jobs-framework entrypoint: read and store the least recently read gadgets."""
    if argv:
        sys.stderr.write("gadget-source: takes no arguments\n")
        return 2
    limit = int(os.environ.get("GADGET_SOURCE_LIMIT") or gadget_source.DEFAULT_LIMIT)
    job_runner.configure()
    return job_runner.run_job(
        "gadget-source",
        lambda: gadget_source.refresh(limit=limit),
        # One wiki refusing a query is already counted rather than raised, so a
        # retry here is only for the database ending the pass under us.
        retry_on_disconnect=True,
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
