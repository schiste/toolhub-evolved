# SPDX-License-Identifier: GPL-3.0-or-later
"""The scheduled rebuild that keeps /statistics off the request path."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import statistics_refresh  # noqa: E402
from backend import db  # noqa: E402
from backend.models import ApiCacheMeta, CanonicalToolCache  # noqa: E402


@pytest.fixture(autouse=True)
def database(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    db.configure("sqlite://")
    db.init_schema()


def test_the_job_stores_a_snapshot_a_request_can_serve_without_rebuilding(capsys):
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

    assert statistics_refresh.main() == 0

    with db.session_scope() as session:
        assert session.get(ApiCacheMeta, "catalog_statistics_v1") is not None
    assert '"stored": true' in capsys.readouterr().out


def test_the_job_refuses_arguments_rather_than_ignoring_them(capsys):
    """`--force` and friends would read as accepted and change nothing."""
    assert statistics_refresh.main(["--force"]) == 2
    assert "takes no arguments" in capsys.readouterr().err
