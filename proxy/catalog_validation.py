# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded Toolforge job for catalog URL reachability validation."""

from __future__ import annotations

import json
import os
import sys

from backend import DEFAULT_DB_URL, catalog_validation, db


def main() -> int:
    db.configure(os.getenv("TOOLHUB_DB_URL", DEFAULT_DB_URL))
    db.init_schema()
    summary = catalog_validation.refresh_candidates(limit=int(os.getenv("CATALOG_VALIDATION_LIMIT", "200")))
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
