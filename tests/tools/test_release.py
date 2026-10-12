# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed tests for the local, exact-SHA Toolforge release coordinator."""

from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import release as release_cli  # noqa: E402


SHA = "a" * 40
OTHER_SHA = "b" * 40
WORKFLOW_IDS = {"CI": 302279857, "CodeQL": 347625467}


def _run(workflow: str, run_id: int, *, sha: str = SHA, branch: str = "main", event: str = "push", status: str = "completed", conclusion: str = "success", created: str = "2026-10-12T12:00:00Z", workflow_id: int | None = None) -> dict[str, object]:
    return {
        "databaseId": run_id,
        "workflowDatabaseId": WORKFLOW_IDS.get(workflow) if workflow_id is None else workflow_id,
        "workflowName": workflow,
        "headSha": sha,
        "headBranch": branch,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "createdAt": created,
        "url": f"https://github.com/schiste/toolhub-evolved/actions/runs/{run_id}",
    }


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _manifest(sha: str) -> dict[str, object]:
    return {"schemaVersion": 3, "deployments": [{"sha": sha, "deployedAt": "2026-10-12T12:00:00Z"}]}


def test_validate_sha_requires_a_full_lowercase_commit_id() -> None:
    assert release_cli.validate_sha(SHA) == SHA

    for invalid in ("abc", "g" * 40, "A" * 40, "a" * 39):
        with pytest.raises(release_cli.ReleaseError, match="40-character lowercase Git SHA"):
            release_cli.validate_sha(invalid)


def test_select_required_runs_uses_only_latest_exact_main_push_runs() -> None:
    rows = [
        _run("CI", 1, created="2026-10-11T12:00:00Z"),
        _run("CI", 2),
        _run("CodeQL", 3),
        _run("CI", 4, sha=OTHER_SHA),
        _run("CodeQL", 5, branch="feature/release"),
        _run("CodeQL", 6, event="pull_request"),
        _run("Production monitor", 7, event="schedule", conclusion="failure"),
    ]

    selected = release_cli.select_required_runs(rows, SHA)

    assert {name: row["databaseId"] for name, row in selected.items()} == {"CI": 2, "CodeQL": 3}


def test_same_display_name_with_wrong_workflow_identity_is_not_a_required_check() -> None:
    rows = [
        _run("CI", 1, workflow_id=999999999),
        _run("CodeQL", 2, workflow_id=999999998),
    ]

    assert release_cli.select_required_runs(rows, SHA) == {}


def test_run_lookup_requests_stable_workflow_identity() -> None:
    assert "workflowDatabaseId" in release_cli.RUN_FIELDS


def test_manifest_requires_a_valid_sha_on_the_current_entry() -> None:
    assert release_cli.deployment_sha(_manifest(SHA)) == SHA

    for payload in ({}, {"deployments": []}, {"deployments": [{"sha": "short"}]}, {"deployments": "bad"}):
        with pytest.raises(release_cli.ReleaseError, match="deployment manifest"):
            release_cli.deployment_sha(payload)


def test_manifest_fetch_requests_cache_revalidation() -> None:
    headers: dict[str, str | None] = {}

    def opener(request: Request, *, timeout: float) -> _Response:
        assert timeout > 0
        headers["cache-control"] = request.get_header("Cache-control")
        headers["pragma"] = request.get_header("Pragma")
        return _Response(_manifest(SHA))

    coordinator = release_cli.ReleaseCoordinator(opener=opener)

    assert coordinator._read_served_sha() == SHA
    assert headers == {"cache-control": "no-cache", "pragma": "no-cache"}


def test_mismatched_approval_is_rejected_before_any_command() -> None:
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    coordinator = release_cli.ReleaseCoordinator(command_runner=runner)

    with pytest.raises(release_cli.ReleaseError, match="approval must exactly match"):
        coordinator.release(SHA, approval_sha=OTHER_SHA)

    assert commands == []


def test_stale_main_stops_before_toolforge_ssh() -> None:
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=OTHER_SHA, stderr="")

    coordinator = release_cli.ReleaseCoordinator(command_runner=runner)

    with pytest.raises(release_cli.ReleaseError, match="main is .* not requested SHA"):
        coordinator.release(SHA, approval_sha=SHA)

    assert len(commands) == 1
    assert commands[0][:2] == ["gh", "api"]


def test_ci_failure_stops_before_toolforge_ssh() -> None:
    commands: list[list[str]] = []
    rows = [_run("CI", 1, conclusion="failure"), _run("CodeQL", 2)]

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        output = SHA if command[:2] == ["gh", "api"] else json.dumps(rows)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    coordinator = release_cli.ReleaseCoordinator(command_runner=runner, discovery_attempts=1, sleeper=lambda _seconds: None)

    with pytest.raises(release_cli.ReleaseError, match="CI.*failure"):
        coordinator.release(SHA, approval_sha=SHA)

    assert not any(command[0] == "ssh" for command in commands)


def test_exact_sha_deploy_and_manifest_readback_are_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    rows = [_run("CI", 101), _run("CodeQL", 102)]
    manifests = iter((_manifest(OTHER_SHA), _manifest(SHA)))
    smoke_calls: list[tuple[str, float]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["gh", "api"]:
            output = SHA
        elif command[:3] == ["gh", "run", "list"]:
            output = json.dumps(rows)
        elif command[0] == "ssh" and "guard=ok" in command[-1]:
            output = "guard=ok\nbranch=main\nhead=" + OTHER_SHA
        elif command[0] == "ssh" and "TOOLHUB_DEPLOY_EXPECTED_SHA=" in command[-1]:
            output = "Done."
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def opener(_request: object, *, timeout: float) -> _Response:
        assert timeout > 0
        return _Response(next(manifests))

    monkeypatch.setattr(release_cli.post_deploy_smoke, "run", lambda base_url, timeout: smoke_calls.append((base_url, timeout)) or [{"name": "readiness", "status": 200}])
    coordinator = release_cli.ReleaseCoordinator(
        command_runner=runner,
        opener=opener,
        sleeper=lambda _seconds: None,
        discovery_attempts=1,
        manifest_attempts=2,
    )

    result = coordinator.release(SHA, approval_sha=SHA)

    deploy_commands = [command for command in commands if command[0] == "ssh" and "TOOLHUB_DEPLOY_EXPECTED_SHA=" in command[-1]]
    assert result["status"] == "deployed"
    assert len(deploy_commands) == 1
    assert SHA in deploy_commands[0][-1]
    assert "become toolhub-evolved" in deploy_commands[0][-1]
    assert smoke_calls == [(release_cli.BASE_URL, release_cli.SMOKE_TIMEOUT_SECONDS)]


def test_dry_run_runs_read_only_preflight_but_never_deploys(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    rows = [_run("CI", 101), _run("CodeQL", 102)]
    smoke_calls: list[str] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["gh", "api"]:
            output = SHA
        elif command[:3] == ["gh", "run", "list"]:
            output = json.dumps(rows)
        elif command[0] == "ssh":
            output = "guard=ok\nbranch=main\nhead=" + OTHER_SHA
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(release_cli.post_deploy_smoke, "run", lambda base_url, timeout: smoke_calls.append(base_url) or [])
    coordinator = release_cli.ReleaseCoordinator(
        command_runner=runner,
        opener=lambda _request, *, timeout: _Response(_manifest(OTHER_SHA)),
        sleeper=lambda _seconds: None,
        discovery_attempts=1,
    )

    result = coordinator.release(SHA, dry_run=True)

    assert result["status"] == "dry_run"
    assert result["smoke"] == []
    assert any(command[0] == "ssh" for command in commands)
    assert not any(command[0] == "ssh" and "TOOLHUB_DEPLOY_EXPECTED_SHA=" in command[-1] for command in commands)
    assert smoke_calls == [release_cli.BASE_URL]


def test_already_deployed_sha_is_idempotent_and_still_smoke_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    rows = [_run("CI", 101), _run("CodeQL", 102)]
    smoke_calls: list[str] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["gh", "api"]:
            output = SHA
        elif command[:3] == ["gh", "run", "list"]:
            output = json.dumps(rows)
        elif command[0] == "ssh":
            output = "guard=ok\nbranch=main\nhead=" + SHA
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(release_cli.post_deploy_smoke, "run", lambda base_url, timeout: smoke_calls.append(base_url) or [])
    coordinator = release_cli.ReleaseCoordinator(
        command_runner=runner,
        opener=lambda _request, *, timeout: _Response(_manifest(SHA)),
        sleeper=lambda _seconds: None,
        discovery_attempts=1,
    )

    result = coordinator.release(SHA, approval_sha=SHA)

    assert result["status"] == "already_deployed"
    assert smoke_calls == [release_cli.BASE_URL]
    assert not any(command[0] == "ssh" and "TOOLHUB_DEPLOY_EXPECTED_SHA=" in command[-1] for command in commands)


def test_manifest_claim_of_target_sha_requires_matching_toolforge_head(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    rows = [_run("CI", 101), _run("CodeQL", 102)]
    smoke_calls: list[str] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["gh", "api"]:
            output = SHA
        elif command[:3] == ["gh", "run", "list"]:
            output = json.dumps(rows)
        else:
            output = "guard=ok\nbranch=main\nhead=" + OTHER_SHA
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(release_cli.post_deploy_smoke, "run", lambda base_url, timeout: smoke_calls.append(base_url) or [])
    coordinator = release_cli.ReleaseCoordinator(
        command_runner=runner,
        opener=lambda _request, *, timeout: _Response(_manifest(SHA)),
        sleeper=lambda _seconds: None,
        discovery_attempts=1,
    )

    with pytest.raises(release_cli.ReleaseError, match="manifest reports .* Toolforge checkout"):
        coordinator.release(SHA, approval_sha=SHA)

    assert smoke_calls == []
    assert not any(command[0] == "ssh" and "TOOLHUB_DEPLOY_EXPECTED_SHA=" in command[-1] for command in commands)


def test_missing_required_workflow_fails_closed_without_ssh() -> None:
    commands: list[list[str]] = []
    rows = [_run("CI", 101)]

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        output = SHA if command[:2] == ["gh", "api"] else json.dumps(rows)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    coordinator = release_cli.ReleaseCoordinator(command_runner=runner, discovery_attempts=2, sleeper=lambda _seconds: None)

    with pytest.raises(release_cli.ReleaseError, match="missing required workflow run.*CodeQL"):
        coordinator.release(SHA, approval_sha=SHA)

    assert not any(command[0] == "ssh" for command in commands)


def test_dirty_toolforge_checkout_fails_before_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    rows = [_run("CI", 101), _run("CodeQL", 102)]

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["gh", "api"]:
            output = SHA
        elif command[:3] == ["gh", "run", "list"]:
            output = json.dumps(rows)
        else:
            output = "guard=dirty\nbranch=main\nhead=" + OTHER_SHA
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(release_cli.post_deploy_smoke, "run", lambda *_args: [])
    coordinator = release_cli.ReleaseCoordinator(command_runner=runner, discovery_attempts=1)

    with pytest.raises(release_cli.ReleaseError, match="Toolforge checkout must be clean"):
        coordinator.release(SHA, approval_sha=SHA)

    assert not any(command[0] == "ssh" and "TOOLHUB_DEPLOY_EXPECTED_SHA=" in command[-1] for command in commands)


def test_pending_workflows_are_watched_once_each_then_read_back() -> None:
    pending = [_run("CI", 101, status="in_progress", conclusion=""), _run("CodeQL", 102, status="queued", conclusion="")]
    completed = [_run("CI", 101), _run("CodeQL", 102)]
    commands: list[list[str]] = []
    watched: list[int] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:3] == ["gh", "run", "list"]:
            output = completed if len(watched) == 2 else pending
        else:
            watched.append(int(command[3]))
            output = ""
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(output) if isinstance(output, list) else output, stderr="")

    coordinator = release_cli.ReleaseCoordinator(command_runner=runner, discovery_attempts=1)

    checks = coordinator._wait_for_required_checks(SHA)

    assert watched == [101, 102]
    assert {name: row["runId"] for name, row in checks.items()} == {"CI": 101, "CodeQL": 102}
