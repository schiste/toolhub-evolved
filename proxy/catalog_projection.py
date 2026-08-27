# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded repair job for Evolved-local catalog projections."""

from __future__ import annotations

import os
import sys

from backend import catalog_projection, job_runner


def main() -> int:
    # Per backend.job_contract: individual projection errors are recorded in
    # the summary and stay eligible for the next bounded pass.
    limit = max(1, int(os.getenv("CATALOG_PROJECTION_LIMIT", str(catalog_projection.MAX_REFRESH_TOOLS))))
    return job_runner.run_job("catalog-projection", lambda: catalog_projection.refresh_candidates(limit=limit))


if __name__ == "__main__":
    sys.exit(main())
