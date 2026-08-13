# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded Toolforge job for rebuilding the local tool icon cache."""

from __future__ import annotations

import json
import os
import sys

from backend import DEFAULT_DB_URL, db, job_contract, tool_assets


def main() -> int:
    db.configure(os.getenv("TOOLHUB_DB_URL", DEFAULT_DB_URL))
    db.init_schema()
    summary = tool_assets.refresh_candidates(limit=int(os.getenv("TOOL_ASSET_LIMIT", "100")))
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    # Individual remote icon failures are durable catalog observations, not a
    # failed sweep -- the rule now stated once in backend.job_contract.
    return job_contract.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
