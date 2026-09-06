# SPDX-License-Identifier: GPL-3.0-or-later
"""The scheduled rebuild that keeps the data-layer page off the request path.

Coverage had the same defect statistics was fixed for and kept it: a six-hour
staleness limit whose only refresh ran every six hours, so the margin was zero
and any late run put a visitor on the hook for a whole-catalogue rebuild.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import coverage_refresh  # noqa: E402
from backend import catalog_coverage, db, job_catalog  # noqa: E402
from backend.models import ApiCacheMeta, CanonicalToolCache  # noqa: E402


@pytest.fixture(autouse=True)
def database(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    db.configure("sqlite://")
    db.init_schema()


def test_the_job_stores_a_snapshot_a_request_can_serve_without_rebuilding():
    with db.session_scope() as session:
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        session.add(
            CanonicalToolCache(
                tool_name="t",
                record={"name": "t", "title": "T"},
                expires_at=now + timedelta(days=1),
                stale_until=now + timedelta(days=2),
            )
        )

    assert coverage_refresh.main() == 0

    with db.session_scope() as session:
        assert session.get(ApiCacheMeta, catalog_coverage.SNAPSHOT_KEY) is not None


def test_the_job_refuses_arguments_rather_than_ignoring_them(capsys):
    """`--force` and friends would read as accepted and change nothing."""
    assert coverage_refresh.main(["--force"]) == 2
    assert "takes no arguments" in capsys.readouterr().err


def test_coverage_is_refreshed_far_more_often_than_it_goes_stale():
    """The defect this job exists for, stated as the invariant it restores.

    Coverage's only refresh was a stage inside `projection-refresh`, whose
    six-hour schedule exactly equalled `SNAPSHOT_STALE_LIMIT`. Equal is not
    enough: a snapshot is stale the instant a run is late, deferred, or fails,
    and the next request pays for the rebuild. A quarter of the limit leaves
    room for three consecutive misses before a visitor notices.
    """
    declared = {job.name: job for job in job_catalog.load()}
    assert "coverage-refresh" in declared, "the data-layer page needs a refresh job of its own"
    interval = timedelta(minutes=declared["coverage-refresh"].expected_interval_minutes)
    assert timedelta(0) < interval <= catalog_coverage.SNAPSHOT_STALE_LIMIT / 4
