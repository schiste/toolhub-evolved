# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded Toolforge job for rebuilding the local tool icon cache."""

from __future__ import annotations

import os
import sys

from backend import job_runner, tool_assets


def main() -> int:
    # Individual remote icon failures are durable catalog observations, not a
    # failed sweep -- the rule stated once in backend.job_contract.
    limit = int(os.getenv("TOOL_ASSET_LIMIT", "100"))
    return job_runner.run_job("tool-assets", lambda: tool_assets.refresh_candidates(limit=limit))


if __name__ == "__main__":
    sys.exit(main())
