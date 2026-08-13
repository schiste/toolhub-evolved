# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for the last-good projection orchestration."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import projection_refresh  # noqa: E402
from backend import db  # noqa: E402
from backend.models import ApiCacheMeta  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_refresh_reuses_fresh_inputs_then_publishes_and_precomputes(monkeypatch):
    order = []
    plan = {"toolhubAccounts": False, "toolforgeAccounts": True, "catalog": False}
    monkeypatch.setattr(projection_refresh, "_sync_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(
        projection_refresh,
        "_parallel_sync",
        lambda actual, _age: order.append(("sync", actual)) or {"toolforgeAccounts": {"status": "idle"}},
    )
    monkeypatch.setattr(
        projection_refresh.people_reconcile,
        "drain_queue",
        lambda **_kwargs: order.append("retire") or {"processed": 0},
    )
    monkeypatch.setattr(projection_refresh, "_identity_fingerprint", lambda: "fingerprint")
    monkeypatch.setattr(projection_refresh, "_identity_is_current", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        projection_refresh,
        "_publish_identity_projection",
        lambda fingerprint, **_kwargs: order.append(("publish", fingerprint)) or {"published": True},
    )
    monkeypatch.setattr(
        projection_refresh.catalog_statistics,
        "snapshot",
        lambda **_kwargs: order.append("statistics")
        or {"generatedAt": "2026-08-13T00:00:00Z", "catalog": {"totalTools": 4473}},
    )

    report = projection_refresh.run(max_age_seconds=123)

    assert report["status"] == "completed"
    assert report["failurePhase"] is None
    assert order == [("sync", plan), "retire", ("publish", "fingerprint"), "statistics"]
    assert report["stages"]["parallelSync"]["plan"] == plan
    assert report["stages"]["statistics"]["metrics"]["totalTools"] == 4473
    with db.session_scope() as session:
        persisted = session.get(ApiCacheMeta, projection_refresh.RUN_META_KEY)
        assert persisted is not None
        assert '"status":"completed"' in persisted.value


def test_refresh_persists_failure_phase_without_publishing(monkeypatch):
    monkeypatch.setattr(
        projection_refresh,
        "_sync_plan",
        lambda *_args, **_kwargs: {"toolhubAccounts": True, "toolforgeAccounts": True, "catalog": True},
    )
    monkeypatch.setattr(
        projection_refresh,
        "_parallel_sync",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("upstream unavailable")),
    )

    with pytest.raises(RuntimeError, match="upstream unavailable"):
        projection_refresh.run()

    with db.session_scope() as session:
        persisted = session.get(ApiCacheMeta, projection_refresh.RUN_META_KEY)
        assert persisted is not None
        assert '"failurePhase":"parallel-sync"' in persisted.value
        assert '"status":"failed"' in persisted.value


def test_job_contract_has_bounded_full_audit_and_retires_old_schedules():
    jobs = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    deploy = (ROOT / "tools" / "deploy.sh").read_text(encoding="utf-8")

    assert "name: projection-refresh" in jobs
    assert "name: source-attestations-full" in jobs
    assert 'timeout: 900' in jobs
    assert "retired_job in account-sync toolforge-account-sync catalog-snapshot" in deploy
    assert "webservice restart" in deploy
    assert "Restart command returned" in deploy
    assert "deployment-diagnostics.jsonl" in deploy


def test_identity_publication_does_not_repeat_network_candidate_discovery(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        projection_refresh.people_reconcile,
        "run",
        lambda _session, **kwargs: captured.update(kwargs) or {"sourceAttestations": {}},
    )
    monkeypatch.setattr(projection_refresh.db, "advisory_lock", lambda *_args, **_kwargs: AcquiredLock())

    with db.session_scope() as session:
        session.add(ApiCacheMeta(key=projection_refresh.IDENTITY_META_KEY, value="old"))
    result = projection_refresh._publish_identity_projection(
        "new",
        changed_since=projection_refresh.EARLIEST_IDENTITY_CHANGE,
    )

    assert result["published"] is True
    assert captured["discover_candidates"] is False


class AcquiredLock:
    def __enter__(self):
        return True

    def __exit__(self, *_args):
        return False
