# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded Toolforge job for catalog URL reachability validation."""

from __future__ import annotations

import os
import sys

from backend import catalog_validation, job_runner


def main() -> int:
    limit = int(os.getenv("CATALOG_VALIDATION_LIMIT", "200"))
    return job_runner.run_job("catalog-validation", lambda: catalog_validation.refresh_candidates(limit=limit))


if __name__ == "__main__":
    sys.exit(main())
