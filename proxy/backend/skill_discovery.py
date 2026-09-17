# SPDX-License-Identifier: GPL-3.0-or-later
"""Discover Agent Skills from a bounded repository observation.

Discovery is deliberately separate from MCP serialization. It turns the files
that repository_scan already acquired into one versioned Evolved catalog
envelope, keeping each skill independent when a sibling has malformed
frontmatter or an unreadable entrypoint.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from backend.skill_catalog import EVOLVED_CATALOG_TYPE, EVOLVED_TOOLINFO_SCHEMA, SKILL_ENTRYPOINT

MAX_PATH_CHARS = 2048
MAX_FRONTMATTER_BYTES = 64 * 1024
MAX_ERROR_CHARS = 500
MIN_QUOTED_SCALAR_CHARS = 2
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MISSING = object()


class SkillDiscoveryError(ValueError):
    """A skill entrypoint or discovery envelope is not usable."""


@dataclass(frozen=True)
class DiscoveryFailure:
    """The isolated failure of one candidate skill."""

    artifact_id: str
    path: str
    error: str
    retryable: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Return the refresh evidence shape."""
        return {
            "id": self.artifact_id,
            "path": self.path,
            "error": self.error[:MAX_ERROR_CHARS],
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class DiscoveryResult:
    """A complete or partial discovery run."""

    catalog: dict[str, Any]
    discovered: int
    failed: int
    observed_files: int


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_path(value: object) -> str:
    raw = _text(value).replace("\\", "/").strip("/")
    if not raw or len(raw) > MAX_PATH_CHARS:
        return ""
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def _content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            message = "file is not valid UTF-8"
            raise SkillDiscoveryError(message) from exc
    message = "file content is not text"
    raise SkillDiscoveryError(message)


def _json_scalar(value: str, kind: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        message = f"frontmatter {kind} is not valid JSON"
        raise SkillDiscoveryError(message) from exc


def _scalar(value: str) -> object:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("["):
        parsed = _json_scalar(value, "list")
        if not isinstance(parsed, list):
            message = "frontmatter list must be an array"
            raise SkillDiscoveryError(message)
        return parsed
    if len(value) >= MIN_QUOTED_SCALAR_CHARS and value[0] == value[-1] == "'":
        return value[1:-1]
    if value.startswith('"'):
        return _json_scalar(value, "string")
    lowered = value.casefold()
    simple = {"true": True, "false": False, "null": None, "~": None}.get(lowered, MISSING)
    return value if simple is MISSING else simple


def _frontmatter_line(values: dict[str, Any], line: str, list_key: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return list_key
    if list_key and stripped.startswith("- "):
        values.setdefault(list_key, []).append(_scalar(stripped[2:]))
        return list_key
    if ":" not in line:
        message = "frontmatter line has no key"
        raise SkillDiscoveryError(message)
    key, raw_value = line.split(":", 1)
    key = key.strip()
    if not KEY_RE.fullmatch(key):
        message = "frontmatter key is invalid"
        raise SkillDiscoveryError(message)
    value = raw_value.strip()
    if value:
        values[key] = _scalar(value)
        return ""
    values[key] = []
    return key


def _normalise_known_frontmatter(values: dict[str, Any]) -> None:
    if "license" in values and not isinstance(values["license"], str):
        message = "frontmatter license must be a string"
        raise SkillDiscoveryError(message)
    if "projects" not in values:
        return
    projects = values["projects"]
    if isinstance(projects, str):
        projects = [projects]
    if not isinstance(projects, list):
        message = "frontmatter projects must be an array"
        raise SkillDiscoveryError(message)
    normalized: list[str] = []
    for project in projects:
        if not isinstance(project, str) or not project.strip():
            message = "frontmatter projects entries must be non-empty strings"
            raise SkillDiscoveryError(message)
        normalized.append(project.strip())
    values["projects"] = list(dict.fromkeys(normalized))


def _frontmatter(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
        message = "SKILL.md frontmatter exceeds the size limit"
        raise SkillDiscoveryError(message)
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        message = "SKILL.md must start with YAML frontmatter"
        raise SkillDiscoveryError(message)
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        message = "SKILL.md frontmatter is not closed"
        raise SkillDiscoveryError(message) from exc

    values: dict[str, Any] = {}
    list_key = ""
    for line in lines[1:end]:
        list_key = _frontmatter_line(values, line, list_key)

    name = _text(values.get("name"))
    description = _text(values.get("description"))
    if not name or not description:
        message = "frontmatter requires name and description"
        raise SkillDiscoveryError(message)
    _normalise_known_frontmatter(values)
    return values


def _source_context(
    source: Mapping[str, Any],
    *,
    commit: str,
    ref: str,
    base_path: str,
) -> dict[str, Any]:
    result = dict(source)
    source_id = _text(result.get("id"))
    repository = _text(result.get("repository"))
    if not source_id or not repository:
        message = "source requires id and repository"
        raise SkillDiscoveryError(message)
    result.update({key: value for key, value in (("commit", commit), ("ref", ref), ("base_path", base_path)) if value})
    return result


def _normalise_files(files: Sequence[Mapping[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    contents: dict[str, str] = {}
    errors: dict[str, str] = {}
    for item in files:
        if not isinstance(item, Mapping):
            continue
        path = _safe_path(item.get("path"))
        if not path or path in contents or path in errors:
            continue
        try:
            contents[path] = _content(item.get("content"))
        except SkillDiscoveryError as exc:
            errors[path] = str(exc)
    return contents, errors


def _root(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    if parent in {"", "."}:
        message = "skill entrypoint must be inside a directory"
        raise SkillDiscoveryError(message)
    return parent


def _resource_paths(root: str, contents: Mapping[str, str], roots: Sequence[str]) -> list[str]:
    prefix = f"{root}/"
    paths = [
        path
        for path in contents
        if path.startswith(prefix)
        and not any(other != root and path.startswith(f"{other}/") for other in roots if other.startswith(prefix))
    ]
    return sorted(paths)


def _resource(path: str, content: str) -> dict[str, Any]:
    body = content.encode("utf-8")
    return {
        "path": path,
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _artifact(
    path: str,
    contents: Mapping[str, str],
    *,
    roots: Sequence[str],
    source: Mapping[str, Any],
    run_id: str,
) -> dict[str, Any]:
    root = _root(path)
    frontmatter = _frontmatter(contents[path])
    artifact_id = f"{source['id']}#{root}"
    resources = [
        _resource(resource_path, contents[resource_path]) for resource_path in _resource_paths(root, contents, roots)
    ]
    if not resources or not any(resource["path"] == path for resource in resources):
        message = "skill resources do not include the root SKILL.md"
        raise SkillDiscoveryError(message)
    artifact: dict[str, Any] = {
        "id": artifact_id,
        "tool_type": "skill",
        "name": frontmatter["name"],
        "description": frontmatter["description"],
        "skill": {
            "root": root,
            "entrypoint": SKILL_ENTRYPOINT,
            "frontmatter": frontmatter,
            "resources": resources,
        },
        "evolved": {
            "review_status": "pending",
            "provenance": {
                "source_kind": "repository_scan",
                "run_id": run_id,
                "commit": source.get("commit", ""),
            },
        },
    }
    projects = frontmatter.get("projects")
    if isinstance(projects, list) and all(isinstance(project, str) and project.strip() for project in projects):
        artifact["projects"] = list(projects)
    return artifact


def discover_catalog(  # noqa: PLR0913 - source and run context fields are independently meaningful evidence
    files: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    *,
    run_id: str,
    commit: str = "",
    ref: str = "",
    base_path: str = "",
) -> DiscoveryResult:
    """Discover all eligible skills in deterministic path order."""
    run_id = _text(run_id)
    if not run_id:
        message = "run_id is required"
        raise SkillDiscoveryError(message)
    context = _source_context(source, commit=commit, ref=ref, base_path=base_path)
    contents, errors = _normalise_files(files)
    entrypoints = sorted(path for path in set(contents) | set(errors) if PurePosixPath(path).name == SKILL_ENTRYPOINT)
    roots = sorted({_root(path) for path in entrypoints if "/" in path})
    artifacts: list[dict[str, Any]] = []
    failures: list[DiscoveryFailure] = []
    for path in entrypoints:
        root = str(PurePosixPath(path).parent)
        artifact_id = f"{context['id']}#{root}"
        if path in errors:
            failures.append(DiscoveryFailure(artifact_id, path, errors[path]))
            continue
        try:
            artifact = _artifact(path, contents, roots=roots, source=context, run_id=run_id)
        except SkillDiscoveryError as exc:
            failures.append(DiscoveryFailure(artifact_id, path, str(exc)))
        else:
            artifacts.append(artifact)
    status = "complete" if not failures else ("partial" if artifacts else "failed")
    refresh: dict[str, Any] = {"run_id": run_id, "status": status}
    if failures:
        refresh["failed_artifacts"] = [failure.as_dict() for failure in failures]
    catalog = {
        "_schema": EVOLVED_TOOLINFO_SCHEMA,
        "type": EVOLVED_CATALOG_TYPE,
        "source": context,
        "refresh": refresh,
        "artifacts": artifacts,
    }
    return DiscoveryResult(catalog, len(artifacts), len(failures), len(contents))
