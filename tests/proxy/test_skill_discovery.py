# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic repository Skill discovery."""

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import skill_catalog, skill_discovery  # noqa: E402


def _source() -> dict[str, str]:
    return {
        "id": "github:example/skills",
        "repository": "https://github.com/example/skills",
    }


def _skill(path: str, name: str, description: str = "A useful skill.", projects: object = None) -> dict[str, object]:
    project_line = ""
    if projects is not None:
        project_line = f"projects: {projects}\n"
    return {
        "path": path,
        "content": f"---\nname: {name}\ndescription: {description}\n{project_line}---\n# {name}\n",
    }


def test_scalar_and_path_helpers_cover_safe_and_unsafe_values(monkeypatch):
    assert skill_discovery._text(" value ") == "value"  # noqa: SLF001
    assert skill_discovery._text(3) == ""  # noqa: SLF001
    assert skill_discovery._safe_path("skills\\alpha\\SKILL.md") == "skills/alpha/SKILL.md"  # noqa: SLF001
    assert skill_discovery._safe_path("") == ""  # noqa: SLF001
    assert skill_discovery._safe_path("/../SKILL.md") == ""  # noqa: SLF001
    assert skill_discovery._safe_path("x" * (skill_discovery.MAX_PATH_CHARS + 1)) == ""  # noqa: SLF001

    assert skill_discovery._content("text") == "text"  # noqa: SLF001
    assert skill_discovery._content(b"text") == "text"  # noqa: SLF001
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="UTF-8"):
        skill_discovery._content(b"\xff")  # noqa: SLF001
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="not text"):
        skill_discovery._content(None)  # noqa: SLF001

    assert skill_discovery._scalar("") == ""  # noqa: SLF001
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="list"):
        skill_discovery._scalar("['one']")  # noqa: SLF001
    assert skill_discovery._scalar("[\"one\", \"two\"]") == ["one", "two"]  # noqa: SLF001
    assert skill_discovery._scalar("'quoted'") == "quoted"  # noqa: SLF001
    assert skill_discovery._scalar('"quoted"') == "quoted"  # noqa: SLF001
    assert skill_discovery._scalar("true") is True  # noqa: SLF001
    assert skill_discovery._scalar("false") is False  # noqa: SLF001
    assert skill_discovery._scalar("null") is None  # noqa: SLF001
    assert skill_discovery._scalar("plain") == "plain"  # noqa: SLF001
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="string"):
        skill_discovery._scalar('"unterminated')  # noqa: SLF001
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="list"):
        skill_discovery._scalar("[not-json")  # noqa: SLF001
    monkeypatch.setattr(skill_discovery.json, "loads", lambda _value: {"not": "a list"})
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="array"):
        skill_discovery._scalar("[object")  # noqa: SLF001


def test_frontmatter_parser_handles_lists_and_rejects_malformed_documents():
    text = """---
name: review
description: "Review changes"
projects:
  - enwiki
  - 'wikidatawiki'
enabled: true
none: null
labels: ["one", "two"]
# ignored
---
body
"""
    values = skill_discovery._frontmatter(text)  # noqa: SLF001
    assert values["name"] == "review"
    assert values["projects"] == ["enwiki", "wikidatawiki"]
    assert values["enabled"] is True
    assert values["none"] is None
    assert values["labels"] == ["one", "two"]
    duplicate_projects = skill_discovery._frontmatter(  # noqa: SLF001
        '---\nname: review\ndescription: review\nprojects: ["enwiki", "enwiki"]\n---'
    )
    assert duplicate_projects["projects"] == ["enwiki"]

    cases = [
        ("body", "start"),
        ("---\nname: review", "closed"),
        ("---\n: value\n---", "key"),
        ("---\nname: review\ninvalid\n---", "no key"),
        ("---\nname: review\n---", "name and description"),
        ("---\ndescription: review\n---", "name and description"),
        ("---\nname: review\ndescription: review\nlicense: true\n---", "license must be"),
        ("---\nname: review\ndescription: review\nprojects: null\n---", "projects must be"),
        ("---\nname: review\ndescription: review\nprojects: [1]\n---", "projects entries"),
        ("---\nname: review\ndescription: review\n---\n" + "x" * skill_discovery.MAX_FRONTMATTER_BYTES, "size"),
    ]
    for invalid, message in cases:
        with pytest.raises(skill_discovery.SkillDiscoveryError, match=message):
            skill_discovery._frontmatter(invalid)  # noqa: SLF001


def test_source_and_file_normalization_is_bounded_and_deterministic():
    context = skill_discovery._source_context(  # noqa: SLF001
        _source(),
        commit="abc123",
        ref="main",
        base_path="skills/",
    )
    assert context["commit"] == "abc123"
    assert context["ref"] == "main"
    assert context["base_path"] == "skills/"
    assert skill_discovery._source_context(_source(), commit="", ref="", base_path="") == _source()  # noqa: SLF001
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="source"):
        skill_discovery._source_context({"id": "missing"}, commit="", ref="", base_path="")  # noqa: SLF001

    contents, errors = skill_discovery._normalise_files(  # noqa: SLF001
        [
            "not a mapping",
            {"path": "../SKILL.md", "content": "ignored"},
            {"path": "README.md", "content": "read me"},
            {"path": "README.md", "content": "duplicate"},
            {"path": "notes.md", "content": b"bytes"},
            {"path": "skills/bad/SKILL.md", "content": b"\xff"},
            {"path": "skills/missing/SKILL.md", "content": None},
        ]
    )
    assert contents == {"README.md": "read me", "notes.md": "bytes"}
    assert set(errors) == {"skills/bad/SKILL.md", "skills/missing/SKILL.md"}


def test_discovery_enumerates_nested_skills_and_isolates_failures():
    files = [
        _skill("skills/alpha/SKILL.md", "alpha", projects='"enwiki"'),
        {"path": "skills/alpha/0.md", "content": "first reference"},
        {"path": "skills/alpha/docs/guide.md", "content": "guide"},
        _skill("skills/alpha/nested/SKILL.md", "nested"),
        {"path": "skills/alpha/nested/ref.md", "content": "nested reference"},
        {"path": "skills/broken/SKILL.md", "content": "not frontmatter"},
        {"path": "skills/bytes/SKILL.md", "content": b"\xff"},
    ]
    first = skill_discovery.discover_catalog(files, _source(), run_id="run-1", commit="abc123")
    second = skill_discovery.discover_catalog(files, _source(), run_id="run-1", commit="abc123")

    assert first.catalog == second.catalog
    assert first.discovered == 2
    assert first.failed == 2
    assert first.observed_files == 6
    assert first.catalog["refresh"]["status"] == "partial"
    assert [artifact["name"] for artifact in first.catalog["artifacts"]] == ["alpha", "nested"]
    alpha = first.catalog["artifacts"][0]
    assert alpha["id"] == "github:example/skills#skills/alpha"
    assert alpha["projects"] == ["enwiki"]
    assert [resource["path"] for resource in alpha["skill"]["resources"]] == [
        "skills/alpha/0.md",
        "skills/alpha/SKILL.md",
        "skills/alpha/docs/guide.md",
    ]
    assert alpha["evolved"]["provenance"] == {
        "source_kind": "repository_scan",
        "run_id": "run-1",
        "commit": "abc123",
    }
    assert alpha["skill"]["resources"][1]["sha256"] == hashlib.sha256(
        b"---\nname: alpha\ndescription: A useful skill.\nprojects: \"enwiki\"\n---\n# alpha\n"
    ).hexdigest()
    assert {failure["path"] for failure in first.catalog["refresh"]["failed_artifacts"]} == {
        "skills/broken/SKILL.md",
        "skills/bytes/SKILL.md",
    }
    entries = skill_catalog._entries_from_record(first.catalog)  # noqa: SLF001
    assert [entry.frontmatter["name"] for entry in entries] == ["alpha", "nested"]
    assert entries[0].catalog_metadata["projects"] == ["enwiki"]


def test_discovery_reports_complete_empty_and_failed_runs():
    empty = skill_discovery.discover_catalog([], _source(), run_id="empty")
    assert empty.catalog["refresh"] == {"run_id": "empty", "status": "complete"}
    assert empty.catalog["artifacts"] == []

    root_skill = skill_discovery.discover_catalog(
        [{"path": "SKILL.md", "content": "---\nname: root\ndescription: root\n---\n"}],
        _source(),
        run_id="root",
    )
    assert root_skill.catalog["refresh"]["status"] == "failed"
    assert root_skill.failed == 1

    with pytest.raises(skill_discovery.SkillDiscoveryError, match="run_id"):
        skill_discovery.discover_catalog([], _source(), run_id=" ")
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="source"):
        skill_discovery.discover_catalog([], {"repository": "https://example.org"}, run_id="bad-source")


def test_discovery_failure_and_resource_helpers_are_serialized(monkeypatch):
    failure = skill_discovery.DiscoveryFailure("id", "path", "x" * (skill_discovery.MAX_ERROR_CHARS + 20))
    payload = failure.as_dict()
    assert payload["id"] == "id"
    assert len(payload["error"]) == skill_discovery.MAX_ERROR_CHARS
    assert payload["retryable"] is True

    monkeypatch.setattr(skill_discovery, "_resource_paths", lambda *_args: [])
    with pytest.raises(skill_discovery.SkillDiscoveryError, match="root SKILL"):
        skill_discovery._artifact(  # noqa: SLF001
            "skills/empty/SKILL.md",
            {
                "skills/empty/SKILL.md": "---\nname: empty\ndescription: empty\n---\n",
            },
            roots=["skills/empty"],
            source=_source(),
            run_id="run",
        )
