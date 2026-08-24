# SPDX-License-Identifier: GPL-3.0-or-later
"""Analyze a local tool source tree and print Toolhub metadata suggestions."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.source_analyzer import (
    IGNORED_SOURCE_DIRS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    SourceAnalysisError,
    analyze_source_files,
    is_supported_source_path,
    order_sources_for_reading,
)

GIT_TIMEOUT_SECONDS = 3


def _ignored_path(path: Path) -> bool:
    return bool({part.lower() for part in path.parts} & IGNORED_SOURCE_DIRS)


def _is_candidate(path: Path) -> bool:
    return is_supported_source_path(path.as_posix())


def _source_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    candidates: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for child in sorted(current.iterdir(), reverse=True):
            if _ignored_path(child):
                continue
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                candidates.append(child)
    return order_sources_for_reading(candidates, lambda path: path.relative_to(root).as_posix(), budget=MAX_FILES)


def _read_tree(paths: list[Path]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    total = 0
    roots = [path.resolve() for path in paths]
    for root in roots:
        if not root.exists():
            message = f"{root}: path does not exist"
            raise OSError(message)
        for path in _source_files(root):
            if len(files) >= MAX_FILES:
                return files
            if not _is_candidate(path):
                continue
            raw = path.read_bytes()
            if len(raw) > MAX_FILE_BYTES:
                continue
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                return files
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            files.append({"path": _relative_label(path, roots), "content": content})
    return files


def _relative_label(path: Path, roots: list[Path]) -> str:
    for root in roots:
        base = root if root.is_dir() else root.parent
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.name


def _analysis_root(paths: list[Path]) -> Path:
    first = paths[0].resolve()
    return first if first.is_dir() else first.parent


def _git_output(root: Path, args: list[str]) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - args are fixed Git subcommands assembled without shell=True.
            [git, *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip()
    return output if result.returncode == 0 and output else None


def _clean_remote_url(value: str | None) -> str | None:
    if value is None:
        return None
    if "@" in value and ":" in value and "://" not in value:
        host, repo = value.split(":", 1)
        host = host.rsplit("@", 1)[-1]
        return f"https://{host}/{repo}"
    return value


def _int_value(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _local_git_context(paths: list[Path]) -> dict[str, Any]:
    root_text = _git_output(_analysis_root(paths), ["rev-parse", "--show-toplevel"])
    if root_text is None:
        return {}
    root = Path(root_text)
    repository: dict[str, Any] = {
        "analyzedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "provider": "local-git",
    }
    values = {
        "url": _clean_remote_url(_git_output(root, ["config", "--get", "remote.origin.url"])),
        "branch": _git_output(root, ["branch", "--show-current"]),
        "commitSha": _git_output(root, ["rev-parse", "HEAD"]),
        "lastCommitAt": _git_output(root, ["log", "-1", "--format=%cI"]),
        "tag": _git_output(root, ["describe", "--tags", "--abbrev=0"]),
    }
    default_branch = _git_output(root, ["symbolic-ref", "refs/remotes/origin/HEAD", "--short"])
    if default_branch:
        values["defaultBranch"] = default_branch.removeprefix("origin/")
    repository.update({key: value for key, value in values.items() if value})
    commit_count = _int_value(_git_output(root, ["rev-list", "--count", "HEAD"]))
    if commit_count is not None:
        repository["commitCount"] = commit_count
    emails = _git_output(root, ["log", "--format=%ae", "--max-count=500"])
    if emails:
        repository["contributorCount"] = len({line.strip().lower() for line in emails.splitlines() if line.strip()})
    status = _git_output(root, ["status", "--porcelain"])
    repository["dirty"] = bool(status)
    return {"repository": repository}


def _read_context_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        message = f"{path}: repository context JSON must be an object"
        raise SourceAnalysisError(message)
    return data


def _merge_context(*contexts: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for context in contexts:
        for key, value in context.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    return merged


def main(argv: list[str] | None = None) -> int:
    """Run the source analyzer for one or more local paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Source file or directory to analyze.")
    parser.add_argument("--tool-name", default="", help="Optional Toolhub tool name to attach to the report.")
    parser.add_argument("--source-label", default="", help="Optional source label, such as a repository URL.")
    parser.add_argument("--context-json", type=Path, help="Optional repository context JSON to merge into the report.")
    parser.add_argument(
        "--no-git-context",
        action="store_true",
        help="Skip deterministic local Git metadata collection.",
    )
    args = parser.parse_args(argv)
    try:
        repository_context = _merge_context(
            {} if args.no_git_context else _local_git_context(args.paths),
            _read_context_json(args.context_json) if args.context_json else {},
        )
        payload: dict[str, Any] = analyze_source_files(
            _read_tree(args.paths),
            tool_name=args.tool_name.strip() or None,
            source_label=args.source_label.strip() or None,
            repository_context=repository_context,
        )
    except (OSError, SourceAnalysisError, json.JSONDecodeError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")
    sys.stdout.write(f"{json.dumps(payload, indent=2, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
