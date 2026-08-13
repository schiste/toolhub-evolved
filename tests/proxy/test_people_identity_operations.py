# SPDX-License-Identifier: GPL-3.0-or-later
"""Deployment coverage for public identity reconciliation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_background_jobs_reconcile_public_identities() -> None:
    jobs = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    deploy = (ROOT / "tools" / "deploy.sh").read_text(encoding="utf-8")

    assert "name: people-identity-reconcile" in jobs
    assert "proxy/people_reconcile.py --identities-only" in jobs
    assert "projection-refresh-deploy" in deploy
    assert "people_reconcile.run" in (ROOT / "proxy" / "projection_refresh.py").read_text(encoding="utf-8")
