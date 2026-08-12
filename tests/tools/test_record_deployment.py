# SPDX-License-Identifier: GPL-3.0-or-later
"""Deployment history is promoted only after production smoke succeeds."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import record_deployment as deployment  # noqa: E402


def reviewed_notes(label: str = "release") -> dict[str, str]:
    bullets = "\n".join(f"- {label} outcome {index}" for index in range(1, 4))
    return {"user": bullets, "technical": bullets}


def fake_git(*args: str) -> str:
    if args == ("rev-parse", "HEAD"):
        return "a" * 40
    if args == ("rev-parse", "--short=12", "HEAD"):
        return "a" * 12
    raise AssertionError(args)


def test_prepare_is_non_mutating_and_promote_persists_exact_manifest(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    public_path = tmp_path / "deployments.json"
    original = [{"id": "old", "sha": "b" * 40, "marketing": reviewed_notes("old")}]
    history_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", reviewed_notes)

    deployment.prepare(public_path, history_path)

    assert json.loads(history_path.read_text(encoding="utf-8")) == original
    staged = json.loads(public_path.read_text(encoding="utf-8"))
    assert staged["schemaVersion"] == 2
    assert [item["sha"] for item in staged["deployments"]] == ["a" * 40, "b" * 40]

    deployment.promote(public_path, history_path)

    assert json.loads(history_path.read_text(encoding="utf-8")) == staged["deployments"]


def test_new_deployment_rejects_reused_or_overlong_notes(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    same = reviewed_notes()
    history_path.write_text(json.dumps([{"sha": "b" * 40, "marketing": same}]), encoding="utf-8")
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", lambda: same)
    with pytest.raises(RuntimeError, match="reuses the previous release notes"):
        deployment.prepare(tmp_path / "same.json", history_path)

    too_many = "\n".join(f"- item {index}" for index in range(9))
    monkeypatch.setattr(deployment, "marketing_notes", lambda: {"user": too_many, "technical": too_many})
    with pytest.raises(RuntimeError, match="3 to 8 bundled entries"):
        deployment.prepare(tmp_path / "many.json", history_path)


def test_history_is_bounded_without_collapsing_to_two(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    history = [{"sha": str(index), "marketing": reviewed_notes(str(index))} for index in range(60)]
    history_path.write_text(json.dumps(history), encoding="utf-8")
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", reviewed_notes)

    staged = deployment.staged_history(history_path)

    assert len(staged) == deployment.MAX_DEPLOYMENTS
    assert staged[0]["sha"] == "a" * 40
    assert staged[-1]["sha"] == "48"
