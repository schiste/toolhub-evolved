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
        lambda actual: order.append(("sync", actual)) or {"toolforgeAccounts": {"status": "idle"}},
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


def test_refresh_persists_input_lock_overlap_as_a_healthy_defer(monkeypatch):
    monkeypatch.setattr(
        projection_refresh,
        "_sync_plan",
        lambda *_args, **_kwargs: {"toolhubAccounts": True, "toolforgeAccounts": True, "catalog": False},
    )
    monkeypatch.setattr(
        projection_refresh,
        "_parallel_sync",
        lambda *_args: (_ for _ in ()).throw(
            projection_refresh.ProjectionRefreshDeferredError(
                "projection already refreshing: toolforgeAccounts, toolhubAccounts"
            )
        ),
    )

    report = projection_refresh.run()

    assert report["status"] == "deferred"
    assert report["failurePhase"] is None
    assert report["reason"] == "projection already refreshing: toolforgeAccounts, toolhubAccounts"
    with db.session_scope() as session:
        persisted = session.get(ApiCacheMeta, projection_refresh.RUN_META_KEY)
        assert persisted is not None
        assert '"status":"deferred"' in persisted.value


def test_parallel_refresh_uses_incremental_catalog_sync(monkeypatch):
    monkeypatch.setattr(
        projection_refresh.catalog_sync,
        "run",
        lambda: {"phase": "steady", "completed": True},
    )
    monkeypatch.setattr(
        projection_refresh.catalog_sync,
        "run_complete",
        lambda **_kwargs: pytest.fail("normal projection refresh must not download a complete catalog"),
    )

    result = projection_refresh._parallel_sync(  # noqa: SLF001 - orchestration contract
        {"toolhubAccounts": False, "toolforgeAccounts": False, "catalog": True}
    )

    assert result["catalog"]["phase"] == "steady"
    assert result["catalog"]["cacheHit"] is False


def test_job_contract_has_bounded_full_audit_and_retires_old_schedules():
    jobs = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    deploy = (ROOT / "tools" / "deploy.sh").read_text(encoding="utf-8")

    assert "name: projection-refresh" in jobs
    assert "name: catalog-integrity" in jobs
    assert 'schedule: "17 3 1,15 * *"' in jobs
    assert "catalog_sync.py --complete" in jobs
    assert "name: source-attestations-full" in jobs
    assert 'timeout: 900' in jobs
    assert "retired_job in account-sync toolforge-account-sync catalog-snapshot" in deploy
    assert "webservice restart" in deploy
    assert "Restart command returned" in deploy
    assert "deployment-diagnostics.jsonl" in deploy
    assert 'deployment_log_dir="$HOME/deployment-logs"' in deploy
    assert 'projection-refresh-$deploy_run_id.out' in deploy
    assert 'ln -sfn "$projection_out" "$HOME/projection-refresh-deploy.out"' in deploy


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


def test_full_source_audit_uses_concurrency_safe_batched_runner(monkeypatch):
    order = []
    monkeypatch.setattr(
        projection_refresh,
        "_sync_plan",
        lambda *_args, **_kwargs: {"toolhubAccounts": False, "toolforgeAccounts": False, "catalog": False},
    )
    monkeypatch.setattr(
        projection_refresh,
        "_parallel_sync",
        lambda *_args: {},
    )
    monkeypatch.setattr(projection_refresh.people_reconcile, "drain_queue", lambda **_kwargs: {})
    monkeypatch.setattr(projection_refresh, "_identity_fingerprint", lambda: "current")
    monkeypatch.setattr(projection_refresh, "_identity_is_current", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        projection_refresh.source_attestations,
        "refresh_full_batched",
        lambda: order.append("source-audit") or {"fullAudit": 1, "batches": 12},
    )
    monkeypatch.setattr(
        projection_refresh.catalog_statistics,
        "snapshot",
        lambda **_kwargs: order.append("statistics")
        or {"generatedAt": "2026-08-14T00:00:00Z", "catalog": {"totalTools": 2}},
    )

    report = projection_refresh.run(full_sources=True)

    assert order == ["source-audit", "statistics"]
    assert report["stages"]["fullSourceAudit"]["metrics"]["batches"] == 12


class AcquiredLock:
    def __enter__(self):
        return True

    def __exit__(self, *_args):
        return False
