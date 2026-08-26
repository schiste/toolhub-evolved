# SPDX-License-Identifier: GPL-3.0-or-later
"""Fill description and keywords for user scripts that have neither."""

from __future__ import annotations

import os
import sys

from backend import inference_enrichment as enrichment
from backend import job_contract, job_runner

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


def _limit() -> int:
    try:
        return max(1, min(MAX_LIMIT, int(os.environ.get("INFERENCE_ENRICHMENT_LIMIT", DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def main() -> int:
    # Per backend.job_contract: pages this pass could not read are recorded
    # against those pages and retried by a later one, so they are not a failed
    # sweep. A missing endpoint is different -- `sweep` raises before asking
    # about anything, so no page was tried and nothing will be retried. Caught
    # rather than left to escape because the operator reading a failing hourly
    # job needs the one line that names the missing variable, not a traceback
    # through requests.
    try:
        return job_runner.run_job("inference-enrichment", lambda: enrichment.sweep(limit=_limit()))
    except RuntimeError as exc:
        sys.stderr.write(f"inference-enrichment: {exc}\n")
        return job_contract.EXIT_SWEEP_FAILED


if __name__ == "__main__":  # pragma: no cover - exercised through main() tests and Toolforge Jobs
    raise SystemExit(main())
