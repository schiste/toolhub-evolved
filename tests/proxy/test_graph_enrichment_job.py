# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the local Toolforge graph-enrichment repair job."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import graph_enrichment as job  # noqa: E402


def _graph_payload():
    return {
        "nodeLimit": 250,
        "nodes": [{"id": "one"}, {"id": "two"}],
        "groupingMeta": [
            {
                "id": "project",
                "covered": 2,
                "total": 2,
                "coverage": 1.0,
                "distinctValues": 2,
                "enabled": True,
            },
            {
                "id": "technology",
                "covered": 2,
                "total": 2,
                "coverage": 1.0,
                "distinctValues": 3,
                "enabled": True,
            },
        ],
        "groupMeta": [
            {"id": "python", "label": "Python", "size": 1},
            {"id": "toolforge", "label": "Toolforge", "size": 1},
            {"id": "compound", "label": "Deno, React", "size": 1},
        ],
    }


def test_main_repairs_locally_and_emits_taxonomy_audit(monkeypatch, capsys):
    calls = []
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.setenv("GRAPH_ENRICHMENT_LIMIT", "5000")
    monkeypatch.setattr(
        job.enrichment,
        "refresh_candidates",
        lambda limit: calls.append(limit)
        or {"candidates": 2, "requested": 2, "refreshed": 2, "changed": 1, "errors": 0},
    )
    monkeypatch.setattr(job.enrichment, "status_summary", lambda: {"enriched": 2})
    monkeypatch.setattr(job.graph_payload, "build", lambda **_kwargs: _graph_payload())

    assert job.main() == 0

    assert calls == [job.MAX_LIMIT]
    line = capsys.readouterr().out.strip()
    assert line.startswith("graph-enrichment: ")
    audit = json.loads(line.removeprefix("graph-enrichment: "))
    assert audit["nodes"] == 2
    assert audit["technologyPlatformLeakage"] == ["Toolforge"]
    assert audit["compoundTechnologyGroups"] == ["Deno, React"]
    assert audit["status"] == {"enriched": 2}


def test_main_reports_materialization_errors_without_failing_the_sweep(monkeypatch, capsys):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.setattr(
        job.enrichment,
        "refresh_candidates",
        lambda **_kwargs: {"candidates": 1, "requested": 1, "refreshed": 0, "changed": 0, "errors": 1},
    )
    monkeypatch.setattr(job.enrichment, "status_summary", lambda: {"error": 1})
    monkeypatch.setattr(job.graph_payload, "build", lambda **_kwargs: _graph_payload())

    # Per backend.job_contract: rows this pass could not enrich are reported
    # and retried next pass, so the sweep itself succeeded and must not count
    # toward the guard's breaker.
    assert job.main() == 0
    assert '"errors": 1' in capsys.readouterr().out


def test_jobs_manifest_runs_graph_enrichment_under_job_guard():
    manifest = (ROOT / "jobs.yaml").read_text()

    assert "- name: graph-enrichment" in manifest
    assert "job_guard.sh --job-name graph-enrichment" in manifest
    assert "GRAPH_ENRICHMENT_LIMIT=500" in manifest
    assert "timeout: 300" in manifest
