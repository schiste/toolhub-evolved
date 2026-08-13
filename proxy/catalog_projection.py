# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded repair job for Evolved-local catalog projections."""

from __future__ import annotations

import json
import os
import sys

from backend import DEFAULT_DB_URL, catalog_projection, db, job_contract


def main() -> int:
    db.configure(os.getenv("TOOLHUB_DB_URL", DEFAULT_DB_URL))
    db.init_schema()
    limit = max(1, int(os.getenv("CATALOG_PROJECTION_LIMIT", "500")))
    summary = catalog_projection.refresh_candidates(limit=limit)
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    # Per backend.job_contract: individual projection errors are recorded in
    # the summary and stay eligible for the next bounded pass.
    return job_contract.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
