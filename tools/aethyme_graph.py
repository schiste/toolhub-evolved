# SPDX-License-Identifier: GPL-3.0-or-later
"""Review and validate committed Aethyme graph fragments."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO, Any, NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_VERSION_FILE = Path(".aethyme/engine-version")
CANONICAL_REPOSITORY = "schiste/toolhub-evolved"
SMOKE_REQUEST = "Where is the Flask application created and which function registers backend configuration?"


def _die(message: str) -> NoReturn:
    raise RuntimeError(message)


def _resolve_binary(env_name: str, default: str) -> str:
    candidate = os.environ.get(env_name) or shutil.which(default)
    if candidate:
        return candidate
    _die(
        f"{default} is required; install the Aethyme release pinned in "
        f"{ENGINE_VERSION_FILE} and expose it through {env_name} or PATH"
    )


def _run(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, text=True, stdout=stdout)  # noqa: S603


def _read_json(args: list[str], *, cwd: Path) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as output:
        _run(args, cwd=cwd, stdout=output)
        output.seek(0)
        try:
            payload = json.load(output)
        except (OSError, json.JSONDecodeError) as error:
            _die(f"Aethyme returned invalid JSON for {' '.join(args[1:4])}: {error}")
    if not isinstance(payload, dict):
        _die(f"Aethyme returned a non-object response for {' '.join(args[1:4])}")
    return payload


def _validate_plan_identity(plan: dict[str, Any], pinned_version: str) -> str:
    """Validate graph authority, runtime, and the plan's digest."""
    policy = plan.get("policy")
    installed = plan.get("installed")
    if not isinstance(policy, dict) or not isinstance(installed, dict):
        _die("Aethyme graph refresh plan is missing policy or runtime evidence")
    if plan.get("canonical_repository") != CANONICAL_REPOSITORY or policy.get("repository") != CANONICAL_REPOSITORY:
        _die(f"Aethyme graph refresh must target {CANONICAL_REPOSITORY}")
    if policy.get("authority") != "committed_fragments":
        _die("committed graph authority is not enabled")
    if policy.get("pinned_engine_version") != pinned_version:
        _die(f"Aethyme graph policy does not match repository pin {pinned_version}")
    runtime_versions = (
        installed.get("router_version"),
        installed.get("linked_engine_version"),
        installed.get("graph_indexer_version"),
    )
    if any(version != pinned_version for version in runtime_versions):
        _die(f"Aethyme runtime does not match repository pin {pinned_version}: {runtime_versions}")
    plan_sha256 = plan.get("plan_sha256")
    if not isinstance(plan_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", plan_sha256) is None:
        _die("Aethyme graph refresh plan has an invalid SHA-256")
    return plan_sha256


def _validate_fragment_count(plan: dict[str, Any]) -> int:
    """Return the plan's validated fragment-change count."""
    fragments = plan.get("fragments")
    if not isinstance(fragments, dict):
        _die("Aethyme graph refresh plan is missing fragment evidence")
    changed_file_count = fragments.get("changed_file_count")
    if not isinstance(changed_file_count, int) or isinstance(changed_file_count, bool) or changed_file_count < 0:
        _die("Aethyme graph refresh plan has an invalid changed-file count")
    return changed_file_count


def _validate_plan_safety(plan: dict[str, Any]) -> int:
    """Reject unsafe plans and return their validated fragment-change count."""
    changed_file_count = _validate_fragment_count(plan)
    if plan.get("safe_to_execute") is not True:
        blockers = plan.get("blockers")
        details = (
            "; ".join(item for item in blockers if isinstance(item, str))
            if isinstance(blockers, list)
            else "no blocker details"
        )
        _die(f"Aethyme graph refresh blocked: {details}")
    return changed_file_count


def _refresh_context(repo: Path) -> tuple[Path, str, str]:
    """Resolve the repository, pinned CLI, and installed router."""
    repo = repo.resolve()
    router = _resolve_binary("AETHYME_BIN", "aethyme")
    try:
        pinned_version = (repo / ENGINE_VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError as error:
        _die(f"cannot read the repository Aethyme engine pin: {error}")
    if not pinned_version:
        _die("the repository Aethyme engine pin is empty")
    return repo, router, pinned_version


def _read_refresh_plan(repo: Path, router: str) -> dict[str, Any]:
    """Ask Aethyme for the digest-bound committed-HEAD refresh plan."""
    return _read_json(
        [router, "graph", "refresh", "plan", "--repo", str(repo), "--json"],
        cwd=repo,
    )


def plan_refresh(repo: Path = REPO_ROOT) -> dict[str, Any]:
    """Print the hash-only change proposal; never apply a refresh."""
    repo, router, pinned_version = _refresh_context(repo)
    plan = _read_refresh_plan(repo, router)
    plan_sha256 = _validate_plan_identity(plan, pinned_version)
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt") as output:
        _run([router, "graph", "refresh", "plan", "--repo", str(repo), "--diff"], cwd=repo, stdout=output)
        output.seek(0)
        preview = output.read()
    diff_digest = re.search(r"(?m)^\s*plan SHA-256: ([0-9a-f]{64})\s*$", preview)
    if diff_digest is None or diff_digest.group(1) != plan_sha256:
        _die("Aethyme plan changed between JSON and diff review; rerun the plan")
    sys.stdout.write(preview)
    sys.stdout.write(
        "Review the hash-only change list, then apply only this exact plan with:\n"
        f"  python3 tools/aethyme_graph.py apply --confirm {plan_sha256}\n"
    )
    return plan


def apply_refresh(repo: Path, confirmation: str) -> dict[str, Any]:
    """Apply only the current plan whose full digest was explicitly reviewed."""
    if re.fullmatch(r"[0-9a-f]{64}", confirmation) is None:
        _die("--confirm must be the full lowercase 64-character plan SHA-256")
    repo, router, pinned_version = _refresh_context(repo)
    plan = _read_refresh_plan(repo, router)
    plan_sha256 = _validate_plan_identity(plan, pinned_version)
    _validate_plan_safety(plan)
    if confirmation != plan_sha256:
        _die("--confirm does not match the reviewed plan; review the current plan again")
    _run(
        [router, "graph", "refresh", "execute", "--repo", str(repo), "--confirm", confirmation],
        cwd=repo,
    )
    return plan


def check_graph(repo: Path = REPO_ROOT) -> None:
    """Verify committed fragments, materialize the local store, and smoke-test."""
    repo, router, pinned_version = _refresh_context(repo)
    plan = _read_refresh_plan(repo, router)
    _validate_plan_identity(plan, pinned_version)
    changed_file_count = _validate_fragment_count(plan)
    if changed_file_count:
        _die(
            f"committed graph fragments are stale ({changed_file_count} change(s)); "
            "review `python3 tools/aethyme_graph.py plan` before applying a digest"
        )
    _run([router, "graph", "materialize", "--repo", str(repo)], cwd=repo)
    _verify_materialized_graph(repo, router)
    explore_smoke(repo, allow_unknown_freshness=True)


def _nonempty_string_list(value: Any) -> bool:
    """Accept only non-empty lists of non-empty strings."""
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def _verify_materialized_graph(repo: Path, router: str) -> None:
    """Require current fragments and a queryable, current derived graph store."""
    status = _read_json([router, "graph", "status", "--repo", str(repo), "--json"], cwd=repo)
    source = status.get("source")
    fragments = status.get("fragments")
    store = status.get("derived_store")
    if status.get("healthy") is not True or status.get("compatibility") != "compatible":
        _die(f"Aethyme graph status is unhealthy or incompatible: {status.get('diagnosis')}")
    source_sha = source.get("head_sha") if isinstance(source, dict) else None
    if not isinstance(source_sha, str) or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source_sha) is None:
        _die("Aethyme graph status is missing a valid full Git revision SHA")
    changed_file_count = fragments.get("changed_file_count") if isinstance(fragments, dict) else None
    if (
        not isinstance(fragments, dict)
        or fragments.get("status") != "passed"
        or isinstance(changed_file_count, bool)
        or not isinstance(changed_file_count, int)
        or changed_file_count != 0
        or fragments.get("working_tree_matches_proposal") is not True
    ):
        _die(f"Aethyme graph fragments are not current: {fragments}")
    if (
        not isinstance(store, dict)
        or store.get("status") != "current"
        or store.get("indexed_commit") != source["head_sha"]
    ):
        _die(f"Aethyme derived graph store is not current: {store}")
    overview = _read_json([router, "graph", "overview", str(repo), "--json-output"], cwd=repo)
    code_areas = overview.get("code_areas")
    representative_code_files = overview.get("representative_code_files")
    if not _nonempty_string_list(code_areas) or not _nonempty_string_list(representative_code_files):
        _die("Aethyme graph overview returned no repository navigation evidence")


def explore_smoke(repo: Path = REPO_ROOT, *, allow_unknown_freshness: bool = False) -> None:
    """Require answer-safe navigation, rejecting stale or unverified freshness."""
    router = _resolve_binary("AETHYME_BIN", "aethyme")
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as output:
        _run(
            [
                router,
                "explore",
                "--repo",
                str(repo),
                "--request",
                SMOKE_REQUEST,
                "--format",
                "answer-json",
                "--show-observability",
                "--depth",
                "0",
            ],
            cwd=repo,
            stdout=output,
        )
        output.seek(0)
        payload = json.load(output)
    readiness = payload.get("observability", {}).get("readiness", {})
    if payload.get("status") != "complete":
        _die(f"Explore smoke did not complete: status={payload.get('status')!r}")
    if payload.get("safe_to_use_as_navigation") is not True or not payload.get("answer"):
        _die("Explore smoke returned no answer-safe navigation evidence")
    freshness_is_unknown_but_verified = (
        allow_unknown_freshness
        and readiness.get("fresh_enough") is False
        and readiness.get("graph_freshness_status") == "unknown"
    )
    if not freshness_is_unknown_but_verified and (
        readiness.get("fresh_enough") is not True or readiness.get("graph_freshness_status") != "fresh"
    ):
        _die(f"Explore smoke freshness is unverified: {readiness}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    plan_parser = subparsers.add_parser("plan", help="print a reviewable, non-mutating graph refresh plan")
    plan_parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    apply_parser = subparsers.add_parser("apply", help="apply one previously reviewed plan digest")
    apply_parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    apply_parser.add_argument("--confirm", required=True, help="full SHA-256 printed by the reviewed plan")
    check_parser = subparsers.add_parser("check", help="verify committed fragments and smoke-test Explore")
    check_parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    if args.mode == "plan":
        plan_refresh(args.repo)
    elif args.mode == "apply":
        plan = apply_refresh(args.repo, args.confirm)
        if _validate_fragment_count(plan):
            sys.stdout.write("Graph fragments changed; review and commit the generated files before checking again.\n")
    else:
        check_graph(args.repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
