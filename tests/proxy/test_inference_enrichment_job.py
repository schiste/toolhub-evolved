# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Toolforge job that reads descriptions off user-script source."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import inference_enrichment as job  # noqa: E402


def _sweep_result(**counts):
    base = {"asked": 0, "ready": 0, "rejected": 0, "error": 0}
    return {
        "counts": {**base, **counts},
        "model": "llm-qwen36-27b",
        "coverage": {"eligiblePages": 37791, "ready": 200, "rejected": 3, "error": 1},
    }


def test_main_reports_what_the_pass_read(monkeypatch, capsys):
    seen = []
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.setattr(
        job.enrichment, "sweep", lambda limit, **_kwargs: seen.append(limit) or _sweep_result(asked=200, ready=196)
    )

    assert job.main() == 0
    assert seen == [job.DEFAULT_LIMIT]
    line = capsys.readouterr().out.strip()
    audit = json.loads(line.removeprefix("inference-enrichment: "))
    assert audit["counts"]["ready"] == 196
    assert audit["coverage"]["eligiblePages"] == 37791


def test_pages_the_model_could_not_answer_do_not_fail_the_sweep(monkeypatch, capsys):
    # Per backend.job_contract: a per-item failure is a durable observation,
    # recorded against that page and retried later, not a failed sweep.
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.setattr(
        job.enrichment, "sweep", lambda limit, **_kwargs: _sweep_result(asked=5, ready=1, rejected=2, error=2)
    )

    assert job.main() == 0
    assert '"error": 2' in capsys.readouterr().out


def test_an_unconfigured_endpoint_fails_the_sweep(monkeypatch):
    # The opposite case: nothing was asked, so there is nothing to record
    # against any page, and a silent success would hide that the corpus is not
    # being enriched at all.
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.delenv("LIFTWING_API_URL", raising=False)
    monkeypatch.delenv("LIFTWING_MODEL", raising=False)
    assert job.main() != 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [("50", 50), ("0", 1), ("999999", job.MAX_LIMIT), ("not a number", job.DEFAULT_LIMIT)],
    ids=["honoured", "floored", "capped", "unparseable"],
)
def test_the_batch_size_is_bounded(monkeypatch, value, expected):
    # The cap is a spend limit on a shared Wikimedia service, so a typo in the
    # job definition must not turn into an unbounded run.
    monkeypatch.setenv("INFERENCE_ENRICHMENT_LIMIT", value)
    assert job._limit() == expected


def test_jobs_manifest_runs_inference_enrichment_under_job_guard():
    manifest = (ROOT / "jobs.yaml").read_text()

    assert "- name: inference-enrichment" in manifest
    assert "job_guard.sh --job-name inference-enrichment" in manifest
    assert "INFERENCE_ENRICHMENT_LIMIT=200" in manifest
    # `exec` so Toolforge's SIGTERM reaches the interpreter and not the sh -c
    # wrapper, which is what makes the guard's cleanup run at all.
    assert "command: exec " in manifest
