#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run one locally approved, exact-SHA Toolforge release."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO
from urllib.error import URLError
from urllib.request import Request, urlopen

import post_deploy_smoke

REPOSITORY = "schiste/toolhub-evolved"
BRANCH = "main"
TOOLFORGE_HOST = "login.toolforge.org"
TOOLFORGE_ACCOUNT = "toolhub-evolved"
BASE_URL = "https://toolhub-evolved.toolforge.org"
MANIFEST_PATH = "/data/deployments.json"
# Repository-specific workflow database IDs pin the checks to their source workflows.
# Update these only when the corresponding workflow files are replaced in GitHub.
REQUIRED_WORKFLOWS = {"CI": 302279857, "CodeQL": 347625467}
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RUN_FIELDS = "databaseId,workflowDatabaseId,workflowName,headSha,headBranch,event,status,conclusion,createdAt,url"
CHECK_DISCOVERY_ATTEMPTS = 36
CHECK_DISCOVERY_INTERVAL_SECONDS = 5
CHECK_TIMEOUT_SECONDS = 60 * 60
SSH_CONNECT_TIMEOUT_SECONDS = 12
DEPLOY_TIMEOUT_SECONDS = 30 * 60
HTTP_TIMEOUT_SECONDS = 20.0
MANIFEST_ATTEMPTS = 30
MANIFEST_INTERVAL_SECONDS = 10
SMOKE_TIMEOUT_SECONDS = 20.0

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
UrlOpener = Callable[..., Any]


class ReleaseError(RuntimeError):
    """A release precondition, deployment, or read-back failed."""


def validate_sha(value: str) -> str:
    """Accept only a full lowercase Git commit ID."""
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise ReleaseError("expected a 40-character lowercase Git SHA")
    return value


def select_required_runs(rows: object, sha: str) -> dict[str, dict[str, Any]]:
    """Choose the newest push run for each required workflow and exact SHA."""
    if not isinstance(rows, list):
        return {}
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = next(
            (workflow for workflow, workflow_id in REQUIRED_WORKFLOWS.items() if row.get("workflowDatabaseId") == workflow_id),
            None,
        )
        if (
            name is None
            or row.get("headSha") != sha
            or row.get("headBranch") != BRANCH
            or row.get("event") != "push"
            or not isinstance(row.get("databaseId"), int)
        ):
            continue
        previous = selected.get(name)
        if previous is None or (str(row.get("createdAt", "")), row["databaseId"]) > (
            str(previous.get("createdAt", "")),
            previous["databaseId"],
        ):
            selected[name] = row
    return selected


def deployment_sha(payload: object) -> str:
    """Read and validate the current release SHA from the public manifest."""
    if not isinstance(payload, dict):
        raise ReleaseError("deployment manifest is not a JSON object")
    deployments = payload.get("deployments")
    if not isinstance(deployments, list) or not deployments or not isinstance(deployments[0], dict):
        raise ReleaseError("deployment manifest has no current deployment")
    sha = deployments[0].get("sha")
    if not isinstance(sha, str):
        raise ReleaseError("deployment manifest current entry has an invalid SHA")
    try:
        return validate_sha(sha)
    except ReleaseError as exc:
        raise ReleaseError("deployment manifest current entry has an invalid SHA") from exc


class ReleaseCoordinator:
    """Coordinate local approval, GitHub checks, Toolforge, and public read-back."""

    def __init__(
        self,
        *,
        command_runner: CommandRunner | None = None,
        opener: UrlOpener | None = None,
        sleeper: Callable[[float], None] | None = None,
        output: TextIO | None = None,
        discovery_attempts: int = CHECK_DISCOVERY_ATTEMPTS,
        discovery_interval: float = CHECK_DISCOVERY_INTERVAL_SECONDS,
        manifest_attempts: int = MANIFEST_ATTEMPTS,
        manifest_interval: float = MANIFEST_INTERVAL_SECONDS,
    ) -> None:
        self.command_runner = command_runner
        self.opener = opener
        self.sleeper = sleeper
        self.output = output or sys.stdout
        self.discovery_attempts = discovery_attempts
        self.discovery_interval = discovery_interval
        self.manifest_attempts = manifest_attempts
        self.manifest_interval = manifest_interval

    def release(self, sha: str, *, approval_sha: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        """Validate the release gates, deploy once when approved, then verify production."""
        sha = validate_sha(sha)
        if approval_sha is not None and approval_sha != sha:
            raise ReleaseError("approval must exactly match the requested SHA")
        if not dry_run and approval_sha != sha:
            raise ReleaseError(f"explicit approval required: pass --approve-sha {sha}")

        self._note(f"Checking GitHub main is {sha} ...")
        self._assert_main_sha(sha)
        checks = self._wait_for_required_checks(sha)
        self._assert_main_sha(sha)

        self._note("Checking the Toolforge checkout is clean and on main ...")
        remote = self._toolforge_command(self._preflight_script(), label="Toolforge preflight", timeout=SSH_CONNECT_TIMEOUT_SECONDS + 30)
        remote_head = self._validate_toolforge_preflight(remote)
        deployed_sha = self._read_served_sha()

        if deployed_sha == sha:
            if remote_head != sha:
                raise ReleaseError(
                    f"manifest reports {sha} but Toolforge checkout is {remote_head}"
                )
            self._note(f"{sha} is already served; verifying production without redeploying.")
            smoke = self._run_production_smoke()
            return self._result("already_deployed", sha, checks, deployed_sha, remote_head, smoke)

        if dry_run:
            smoke = self._run_production_smoke()
            self._note(f"Dry run complete: would deploy {sha}; no deployment command was sent.")
            return self._result("dry_run", sha, checks, deployed_sha, remote_head, smoke)

        self._assert_main_sha(sha)
        self._note(f"Deploying exactly {sha} with tools/deploy.sh ...")
        self._toolforge_command(self._deploy_script(sha), label="Toolforge deployment", timeout=DEPLOY_TIMEOUT_SECONDS)
        self._note("Waiting for the public manifest to serve the approved SHA ...")
        self._wait_for_served_sha(sha)
        smoke = self._run_production_smoke()
        self._note("Public SHA, readiness, catalog, capabilities, and anonymous write guard verified.")
        return self._result("deployed", sha, checks, sha, remote_head, smoke)

    def _note(self, message: str) -> None:
        print(message, file=self.output, flush=True)

    def _execute(
        self,
        command: Sequence[str],
        *,
        label: str,
        timeout: int,
        capture_output: bool = True,
    ) -> str:
        runner = self.command_runner or subprocess.run
        try:
            result = runner(
                list(command),
                check=False,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReleaseError(f"{label} exceeded its {timeout}s timeout") from exc
        except OSError as exc:
            raise ReleaseError(f"{label} could not start: {exc}") from exc
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            suffix = f": {details[:500]}" if details else ""
            raise ReleaseError(f"{label} failed with exit code {result.returncode}{suffix}")
        return (result.stdout or "").strip()

    def _assert_main_sha(self, sha: str) -> None:
        actual = self._execute(
            ["gh", "api", f"repos/{REPOSITORY}/branches/{BRANCH}", "--jq", ".commit.sha"],
            label="GitHub main lookup",
            timeout=30,
        )
        try:
            actual = validate_sha(actual)
        except ReleaseError as exc:
            raise ReleaseError("GitHub main lookup did not return a full commit SHA") from exc
        if actual != sha:
            raise ReleaseError(f"main is {actual}, not requested SHA {sha}")

    def _list_runs(self, sha: str) -> list[dict[str, Any]]:
        raw = self._execute(
            [
                "gh",
                "run",
                "list",
                "--repo",
                REPOSITORY,
                "--commit",
                sha,
                "--limit",
                "100",
                "--json",
                RUN_FIELDS,
            ],
            label="GitHub workflow-run lookup",
            timeout=30,
        )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReleaseError("GitHub returned invalid workflow-run JSON") from exc
        if not isinstance(value, list):
            raise ReleaseError("GitHub workflow-run lookup did not return a list")
        return value

    def _wait_for_required_checks(self, sha: str) -> dict[str, dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        missing = set(REQUIRED_WORKFLOWS)
        for attempt in range(self.discovery_attempts):
            selected = select_required_runs(self._list_runs(sha), sha)
            missing = set(REQUIRED_WORKFLOWS) - selected.keys()
            if not missing:
                break
            if attempt + 1 < self.discovery_attempts:
                self._note(f"Waiting for GitHub to publish run(s): {', '.join(sorted(missing))} ...")
                (self.sleeper or time.sleep)(self.discovery_interval)
        if missing:
            raise ReleaseError(f"missing required workflow run(s) for {sha}: {', '.join(sorted(missing))}")

        for name in REQUIRED_WORKFLOWS:
            row = selected[name]
            if row.get("status") == "completed" and row.get("conclusion") != "success":
                raise ReleaseError(f"{name} run #{row['databaseId']} concluded {row.get('conclusion')!r}")
            if row.get("status") != "completed":
                self._note(f"Watching {name} run #{row['databaseId']} ...")
                self._execute(
                    ["gh", "run", "watch", str(row["databaseId"]), "--repo", REPOSITORY, "--exit-status"],
                    label=f"{name} run #{row['databaseId']}",
                    timeout=CHECK_TIMEOUT_SECONDS,
                    capture_output=False,
                )

        final = select_required_runs(self._list_runs(sha), sha)
        missing = set(REQUIRED_WORKFLOWS) - final.keys()
        if missing:
            raise ReleaseError(f"required workflow run(s) disappeared for {sha}: {', '.join(sorted(missing))}")
        for name in REQUIRED_WORKFLOWS:
            row = final[name]
            if row.get("status") != "completed" or row.get("conclusion") != "success":
                raise ReleaseError(f"{name} run #{row['databaseId']} is not successful")
        return {
            name: {"runId": final[name]["databaseId"], "url": final[name].get("url")}
            for name in REQUIRED_WORKFLOWS
        }

    @staticmethod
    def _preflight_script() -> str:
        return (
            'set -eu; cd "$HOME/repo"; '
            'if [ "$(git branch --show-current)" != "main" ]; then printf "guard=wrong-branch\\n"; exit 2; fi; '
            'if ! toolforge_status=$(git status --porcelain); then printf "guard=status-failed\\n" >&2; exit 4; fi; '
            'if [ -n "$toolforge_status" ]; then printf "guard=dirty\\n"; git status --short; exit 3; fi; '
            'printf "guard=ok\\nbranch=%s\\nhead=%s\\n" "$(git branch --show-current)" "$(git rev-parse HEAD)"'
        )

    @staticmethod
    def _deploy_script(sha: str) -> str:
        sha = validate_sha(sha)
        return f'cd "$HOME/repo" && TOOLHUB_DEPLOY_EXPECTED_SHA={sha} sh "$HOME/repo/tools/deploy.sh"'

    def _toolforge_command(self, script: str, *, label: str, timeout: int) -> str:
        remote = f"become {TOOLFORGE_ACCOUNT} sh -lc {shlex.quote(script)}"
        return self._execute(
            [
                "ssh",
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}",
                "-o",
                "ServerAliveInterval=30",
                "-o",
                "ServerAliveCountMax=10",
                TOOLFORGE_HOST,
                remote,
            ],
            label=label,
            timeout=timeout,
            capture_output=(label != "Toolforge deployment"),
        )

    @staticmethod
    def _validate_toolforge_preflight(output: str) -> str:
        fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if fields.get("guard") != "ok" or fields.get("branch") != BRANCH:
            raise ReleaseError("Toolforge checkout must be clean and on main")
        try:
            return validate_sha(fields.get("head", ""))
        except ReleaseError as exc:
            raise ReleaseError("Toolforge preflight did not return a valid checkout SHA") from exc

    def _read_served_sha(self) -> str:
        request = Request(
            f"{BASE_URL}{MANIFEST_PATH}",
            headers={"Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        opener = self.opener or urlopen
        try:
            with opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise ReleaseError(f"could not read public deployment manifest: {exc}") from exc
        return deployment_sha(payload)

    def _wait_for_served_sha(self, sha: str) -> None:
        last_seen = "unavailable"
        for attempt in range(self.manifest_attempts):
            try:
                last_seen = self._read_served_sha()
            except ReleaseError as exc:
                last_seen = str(exc)
            if last_seen == sha:
                return
            if attempt + 1 < self.manifest_attempts:
                (self.sleeper or time.sleep)(self.manifest_interval)
        raise ReleaseError(f"public deployment manifest did not serve {sha}; last result: {last_seen}")

    @staticmethod
    def _run_production_smoke() -> list[dict[str, Any]]:
        try:
            return post_deploy_smoke.run(BASE_URL, SMOKE_TIMEOUT_SECONDS)
        except (OSError, ValueError) as exc:
            raise ReleaseError(f"production smoke check failed: {exc}") from exc

    @staticmethod
    def _result(
        status: str,
        sha: str,
        checks: Mapping[str, Mapping[str, Any]],
        deployed_sha: str,
        remote_head: str,
        smoke: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "status": status,
            "sha": sha,
            "checks": dict(checks),
            "toolforgeHeadBeforeDeploy": remote_head,
            "servedSha": deployed_sha,
            "smoke": list(smoke),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True, help="full current main commit SHA")
    parser.add_argument("--approve-sha", help="explicit human approval, repeated exactly for the SHA")
    parser.add_argument("--dry-run", action="store_true", help="run read-only gates and production checks only")
    args = parser.parse_args(argv)
    try:
        result = ReleaseCoordinator().release(args.sha, approval_sha=args.approve_sha, dry_run=args.dry_run)
    except ReleaseError as exc:
        print(f"release blocked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
