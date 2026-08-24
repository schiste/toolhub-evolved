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


def release_metadata(label: str = "directory") -> dict[str, str]:
    return {"id": label, "title": f"{label.title()} release"}


def fake_git(*args: str) -> str:
    if args == ("rev-parse", "HEAD"):
        return "a" * 40
    if args == ("rev-parse", "--short=12", "HEAD"):
        return "a" * 12
    raise AssertionError(args)


def test_prepare_is_non_mutating_and_promote_persists_exact_manifest(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    public_path = tmp_path / "deployments.json"
    original = [
        {
            "id": "old",
            "releaseId": "old",
            "title": "Old release",
            "sha": "b" * 40,
            "marketing": reviewed_notes("old"),
        }
    ]
    history_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", reviewed_notes)
    monkeypatch.setattr(deployment, "release_metadata", release_metadata)

    deployment.prepare(public_path, history_path)

    assert json.loads(history_path.read_text(encoding="utf-8")) == original
    staged = json.loads(public_path.read_text(encoding="utf-8"))
    assert staged["schemaVersion"] == 3
    assert [item["sha"] for item in staged["deployments"]] == ["a" * 40, "b" * 40]

    deployment.promote(public_path, history_path)

    assert json.loads(history_path.read_text(encoding="utf-8")) == staged["deployments"]


def test_new_release_rejects_reused_or_overlong_notes(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    same = reviewed_notes()
    history_path.write_text(json.dumps([{"releaseId": "old", "sha": "b" * 40, "marketing": same}]), encoding="utf-8")
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", lambda: same)
    monkeypatch.setattr(deployment, "release_metadata", release_metadata)
    with pytest.raises(RuntimeError, match="reuses previous release notes"):
        deployment.prepare(tmp_path / "same.json", history_path)

    too_many = "\n".join(f"- item {index}" for index in range(9))
    monkeypatch.setattr(deployment, "marketing_notes", lambda: {"user": too_many, "technical": too_many})
    with pytest.raises(RuntimeError, match="3 to 8 bundled entries"):
        deployment.prepare(tmp_path / "many.json", history_path)


def test_history_is_bounded_without_collapsing_to_two(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    history = [
        {"releaseId": f"release-{index}", "sha": str(index), "marketing": reviewed_notes(str(index))}
        for index in range(60)
    ]
    history_path.write_text(json.dumps(history), encoding="utf-8")
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", reviewed_notes)
    monkeypatch.setattr(deployment, "release_metadata", release_metadata)

    staged = deployment.staged_history(history_path)

    assert len(staged) == deployment.MAX_DEPLOYMENTS
    assert staged[0]["sha"] == "a" * 40
    assert staged[-1]["sha"] == "48"


def test_same_release_updates_serving_build_without_creating_a_version(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            [
                {
                    "id": "directory",
                    "releaseId": "directory",
                    "title": "Directory release",
                    "sha": "b" * 40,
                    "deployedAt": "2026-08-10T00:00:00Z",
                    "releasedAt": "2026-08-09T00:00:00Z",
                    "marketing": reviewed_notes("old"),
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", reviewed_notes)
    monkeypatch.setattr(deployment, "release_metadata", release_metadata)

    staged = deployment.staged_history(history_path)

    assert len(staged) == 1
    assert staged[0]["sha"] == "a" * 40
    assert staged[0]["releasedAt"] == "2026-08-09T00:00:00Z"
    assert staged[0]["marketing"] == reviewed_notes()


def test_legacy_deployment_rows_are_retired(tmp_path, monkeypatch):
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps([{"id": "commit-sha", "sha": "b" * 40, "changes": [{"subject": "fix people"}]}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(deployment, "git", fake_git)
    monkeypatch.setattr(deployment, "marketing_notes", reviewed_notes)
    monkeypatch.setattr(deployment, "release_metadata", release_metadata)

    staged = deployment.staged_history(history_path)

    assert [item["releaseId"] for item in staged] == ["directory"]


def test_check_reports_the_rule_and_writes_nothing(tmp_path, monkeypatch, capsys):
    too_many = "\n".join(f"- item {index}" for index in range(9))
    monkeypatch.setattr(deployment, "marketing_notes", lambda: {"user": too_many, "technical": too_many})
    monkeypatch.setattr(deployment, "release_metadata", release_metadata)

    with pytest.raises(SystemExit) as failure:
        deployment.check()

    assert failure.value.code == 1
    assert "3 to 8 bundled entries" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_check_accepts_the_notes_this_repository_ships(capsys):
    """The files a push would carry must satisfy the rules deploy.sh applies."""
    deployment.check()

    assert "within the bullet cap" in capsys.readouterr().out


def test_pre_push_runs_the_check_unconditionally():
    hook = (ROOT / ".githooks/pre-push").read_text(encoding="utf-8")
    invocation = "python3 tools/record_deployment.py --check"

    assert invocation in hook
    # Indented lines belong to the changelog-provider branch, which is skipped
    # when a raw MCP provider is configured -- exactly the push that shipped the
    # nine-bullet file.
    assert any(line == invocation for line in hook.splitlines())
