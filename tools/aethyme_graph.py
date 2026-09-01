# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild the committed Aethyme graph and smoke-test Explore."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import IO, NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH_DIR = Path(".aethyme/graph")
ENGINE_VERSION_FILE = Path(".aethyme/engine-version")
ENGINE_VERSION = "0.4.2"
INDEXER_REVISION = "d3af42260b1de174c286b7fe749f9f7f597ad429"
REPO_NAME = "toolhub-evolved"
SMOKE_REQUEST = "Where is the Flask application created and which function registers backend configuration?"
EXTRA_IGNORE_DIRS = (
    ".chau7",
    ".jscpd",
    ".playwright-mcp",
    ".pytest_cache",
    ".quality",
    ".ruff_cache",
    ".stryker-tmp",
    ".aethyme/locks",
    ".aethyme/logs",
    ".aethyme/reports",
    ".aethyme/run",
    ".aethyme/worktrees",
    ".venv-ci",
    "backend",
    "coverage",
    "dist",
    "dist.tmp",
    "htmlcov",
    "mutants",
    "output",
    "playwright-report",
    "proxy/var",
    "reports",
    "test-results",
)


def _die(message: str) -> NoReturn:
    raise RuntimeError(message)


def _resolve_binary(env_name: str, default: str) -> str:
    candidate = os.environ.get(env_name) or shutil.which(default)
    if candidate:
        return candidate
    _die(
        f"{default} is required; build the graph indexer from Aethyme revision "
        f"{INDEXER_REVISION} and expose it through {env_name} or PATH"
    )


def _run(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, text=True, stdout=stdout)  # noqa: S603


def rebuild(repo: Path = REPO_ROOT) -> None:
    """Replace graph fragments atomically enough to restore the old set on failure."""
    indexer = _resolve_binary("AETHYME_GRAPH_INDEX_BIN", "aethyme-graph-index")
    engine = _resolve_binary("AETHYME_ENGINE_BIN", "aethyme-engine-cli")
    graph = repo / GRAPH_DIR
    backup_root = Path(tempfile.mkdtemp(prefix="toolhub-aethyme-graph-"))
    backup = backup_root / "graph"
    succeeded = False
    try:
        if graph.exists():
            graph.rename(backup)
        index_args = [
            indexer,
            "--repo-root",
            str(repo),
            "--repo-name",
            REPO_NAME,
            "--engine-version",
            ENGINE_VERSION,
        ]
        for ignored in EXTRA_IGNORE_DIRS:
            index_args.extend(("--extra-ignore", ignored))
        index_args.append("--json")
        _run(index_args, cwd=repo)
        _run([engine, "index", "--repo", str(repo)], cwd=repo)
        succeeded = True
    finally:
        if not succeeded:
            if graph.exists():
                shutil.rmtree(graph)
            if backup.exists():
                backup.rename(graph)
        shutil.rmtree(backup_root)


def assert_generated_clean(repo: Path = REPO_ROOT) -> None:
    """Fail when regeneration changed or introduced a committed graph artifact."""
    result = subprocess.run(  # noqa: S603 - fixed git status invocation
        [  # noqa: S607 - fixed git executable resolved by the environment
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            str(GRAPH_DIR),
            str(ENGINE_VERSION_FILE),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        _die(f"Aethyme graph is stale; run `python3 tools/aethyme_graph.py rebuild`:\n{result.stdout.rstrip()}")


def explore_smoke(repo: Path = REPO_ROOT) -> None:
    """Prove the rebuilt store is fresh and returns bounded navigation evidence."""
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
    if not payload.get("safe_to_use_as_navigation") or not payload.get("answer"):
        _die("Explore smoke returned no answer-safe navigation evidence")
    if readiness.get("fresh_enough") is not True or readiness.get("graph_freshness_status") != "fresh":
        _die(f"Explore smoke used a stale graph: {readiness}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("rebuild", "check"))
    args = parser.parse_args()
    rebuild()
    if args.mode == "check":
        assert_generated_clean()
    explore_smoke()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
