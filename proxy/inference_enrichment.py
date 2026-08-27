# SPDX-License-Identifier: GPL-3.0-or-later
"""Fill description and keywords for user scripts that have neither."""

from __future__ import annotations

import os
import sys

from backend import inference_enrichment as enrichment
from backend import job_contract, job_runner, run_budget

DEFAULT_LIMIT = enrichment.BATCH
# The safety cap, not the bound that decides a run: `sweep` stops on its budget.
# It sits above what one budgeted run can reach so that a fast endpoint is
# limited by the deadline rather than by a number nobody remeasured.
MAX_LIMIT = 20_000


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
    budget = run_budget.from_env("INFERENCE_ENRICHMENT_BUDGET_SECONDS", enrichment.DEFAULT_BUDGET)
    try:
        return job_runner.run_job(
            "inference-enrichment",
            lambda: enrichment.sweep(limit=_limit(), budget=budget),
        )
    except RuntimeError as exc:
        sys.stderr.write(f"inference-enrichment: {exc}\n")
        return job_contract.EXIT_SWEEP_FAILED


if __name__ == "__main__":  # pragma: no cover - exercised through main() tests and Toolforge Jobs
    raise SystemExit(main())
