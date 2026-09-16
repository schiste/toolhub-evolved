# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit coverage for the Evolved skill catalog normalizer."""

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import skill_catalog  # noqa: E402


def _skill_uri(root="lookup"):
    return f"skill://toolhub-evolved/catalog/example/{root}/SKILL.md"


def _resource(uri, content=b"# Skill\n", **extra):
    return {
        "uri": uri,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content": content,
        **extra,
    }


def _skill_candidate(*, name="lookup", root="skills/lookup", resources=None, **extra):
    uri = _skill_uri(name)
    skill = {
        "name": name,
        "description": f"Use the {name} skill.",
        "root": root,
        "resources": resources or [_resource(uri)],
    }
    source = {"id": "github:example/skills", "repository": "https://github.com/example/skills"}
    return {
        "tool_type": "skill",
        "id": f"github:example/skills#{root}",
        "name": name,
        "description": skill["description"],
        "skill": skill,
        "source": source,
        "evolved": {"mcp": {"resource_uri": uri}, "review_status": "approved"},
        **extra,
    }


def test_resource_and_entry_serializers_cover_optional_metadata_and_dynamic_resources():
    uri = _skill_uri()
    sparse = skill_catalog.SkillResource(uri, "SKILL.md", "text/markdown", None, None, None)
    assert sparse.manifest() == {"uri": uri}
    assert sparse.listing() == {"uri": uri, "name": "SKILL.md", "mimeType": "text/markdown"}

    digest = "sha256:" + "a" * 64
    rich = skill_catalog.SkillResource(uri, "SKILL.md", "text/markdown", 3, digest, b"abc", "Read this")
    assert rich.manifest() == {"uri": uri, "size": 3, "digest": digest}
    assert rich.listing() == {
        "uri": uri,
        "name": "SKILL.md",
        "mimeType": "text/markdown",
        "description": "Read this",
        "size": 3,
        "_meta": {f"{skill_catalog.SKILLS_EXTENSION}/digest": digest},
    }

    dynamic = skill_catalog.SkillEntry(uri, {"name": "lookup"}, "dynamic", "", {}, {}, {})
    assert dynamic.public_entry() == {"uri": uri, "frontmatter": {"name": "lookup"}, "resources": "dynamic"}
    assert dynamic.resource(uri) is None

    static = skill_catalog.SkillEntry(
        uri,
        {"name": "lookup"},
        (rich,),
        "artifact-1",
        {"commit": "abc"},
        {"review_status": "approved"},
        {"projects": ["enwiki"]},
    )
    public = static.public_entry()
    assert public["resources"] == [rich.manifest()]
    assert public["_meta"][f"{skill_catalog.SKILLS_EXTENSION}/artifactId"] == "artifact-1"
    assert public["_meta"][f"{skill_catalog.SKILLS_EXTENSION}/source"] == {"commit": "abc"}
    assert public["_meta"][f"{skill_catalog.SKILLS_EXTENSION}/evolved"] == {"review_status": "approved"}
    assert public["_meta"][f"{skill_catalog.SKILLS_EXTENSION}/catalog"] == {"projects": ["enwiki"]}
    assert static.resource(uri) is rich


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("", "missing or too long"),
        ("x" * (skill_catalog.MAX_URI_LENGTH + 1), "missing or too long"),
        ("root/SKILL.md", "scheme"),
        ("skill://ns/root/SKILL.md?lang=fr", "scheme"),
        ("skill://ns/root/SKILL.md#fragment", "scheme"),
        ("skill:///root/SKILL.md", "namespace"),
        ("skill://ns/root/%2E%2E/SKILL.md", "unsafe path segment"),
        ("skill://ns/root/README.md", "end with a skill root"),
    ],
)
def test_normalise_uri_rejects_unsafe_or_incomplete_uris(uri, message):
    with pytest.raises(skill_catalog.InvalidSkillError, match=message):
        skill_catalog._normalise_uri(uri)  # noqa: SLF001


def test_generated_uris_and_resource_paths_are_namespaced_and_safe():
    source = {"id": "GitHub:Example/Skills"}
    assert skill_catalog._source_slug(source) == "github/example/skills"  # noqa: SLF001
    assert skill_catalog._source_slug({}) == "catalog"  # noqa: SLF001
    assert skill_catalog._source_id({"repository": "repo"}) == "repo"  # noqa: SLF001
    assert skill_catalog._generated_uri("lookup", source, "skills/lookup") == (
        "skill://toolhub-evolved/catalog/github/example/skills/skills/lookup/SKILL.md"
    )  # noqa: SLF001
    assert skill_catalog._generated_uri("lookup", source, "skills/other") == (  # noqa: SLF001
        "skill://toolhub-evolved/catalog/github/example/skills/lookup/SKILL.md"
    )

    uri = _skill_uri()
    root = skill_catalog._skill_root(uri)  # noqa: SLF001
    assert skill_catalog._resource_relative(uri, uri) == "SKILL.md"  # noqa: SLF001
    assert skill_catalog._resource_relative(f"{root}/references/api%20guide.md", uri) == "references/api guide.md"  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="outside"):
        skill_catalog._resource_relative("skill://toolhub-evolved/catalog/example/other.md", uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="unsafe"):
        skill_catalog._resource_relative(f"{root}/../other.md", uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="query"):
        skill_catalog._resource_relative(f"{root}/reference.md?raw=1", uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="unsafe"):
        skill_catalog._resource_relative(f"{root}/%2E%2E/reference.md", uri)  # noqa: SLF001

    assert skill_catalog._relative_path("", "skills/lookup") == ""  # noqa: SLF001
    assert skill_catalog._relative_path("/skills/lookup/", "skills/lookup") == ""  # noqa: SLF001
    assert skill_catalog._relative_path("skills/lookup/docs/api.md", "skills/lookup") == "docs/api.md"  # noqa: SLF001
    assert skill_catalog._relative_path("docs/api.md", "skills/lookup") == "docs/api.md"  # noqa: SLF001
    assert skill_catalog._relative_path("skills/lookup/../api.md", "skills/lookup") == ""  # noqa: SLF001


def test_inline_and_container_bodies_are_supported_without_reading_disk():
    assert skill_catalog._body(b"bytes") == b"bytes"  # noqa: SLF001
    assert skill_catalog._body("text") == b"text"  # noqa: SLF001
    assert skill_catalog._body(123) is None  # noqa: SLF001

    assert skill_catalog._content_for({"text": "from text"}, {}, {}) == b"from text"  # noqa: SLF001
    assert skill_catalog._content_for({"body": "from body"}, {}, {}) == b"from body"  # noqa: SLF001
    path = "skills/lookup/references/api.md"
    assert skill_catalog._content_for({"path": path}, {"contents": {path: "from skill"}}, {}) == b"from skill"  # noqa: SLF001
    assert (
        skill_catalog._content_for({"relative_path": "api.md"}, {}, {"files": {"api.md": b"from candidate"}})
        == b"from candidate"
    )  # noqa: SLF001
    assert skill_catalog._content_for({"path": "missing.md"}, {"contents": []}, {"files": {}}) is None  # noqa: SLF001


def test_resource_metadata_normalization_and_limits_are_enforced():
    digest = "a" * 64
    assert skill_catalog._digest(f"SHA256:{digest}") == f"sha256:{digest}"  # noqa: SLF001
    assert skill_catalog._digest("not-a-digest") is None  # noqa: SLF001
    assert skill_catalog._size(True) is None  # noqa: SLF001
    assert skill_catalog._size("not-a-number") is None  # noqa: SLF001
    assert skill_catalog._size(-1) is None  # noqa: SLF001
    assert skill_catalog._size("3") == 3  # noqa: SLF001
    assert skill_catalog._mime({"mimeType": "text/custom"}, "file.bin") == "text/custom"  # noqa: SLF001
    assert skill_catalog._mime({}, "SKILL.md") == "text/markdown"  # noqa: SLF001
    assert skill_catalog._mime({}, "notes.txt") == "text/plain"  # noqa: SLF001
    assert skill_catalog._mime({}, "notes.zzz-nobody") == skill_catalog._MIME_FALLBACK  # noqa: SLF001

    uri = _skill_uri()
    root = skill_catalog._skill_root(uri)  # noqa: SLF001
    assert skill_catalog._resource_uri({"uri": uri}, "", uri, first=False) == uri  # noqa: SLF001
    assert skill_catalog._resource_uri({}, "references/api.md", uri, first=False) == f"{root}/references/api.md"  # noqa: SLF001
    assert skill_catalog._resource_uri({}, "", uri, first=True) == uri  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="neither uri nor path"):
        skill_catalog._resource_uri({}, "", uri, first=False)  # noqa: SLF001

    content = b"abc"
    valid = {"size": 3, "sha256": hashlib.sha256(content).hexdigest()}
    assert skill_catalog._resource_digest_and_size(valid, content) == (3, f"sha256:{valid['sha256']}")  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="size"):
        skill_catalog._resource_digest_and_size({"size": 4}, content)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="digest"):
        skill_catalog._resource_digest_and_size({"sha256": "0" * 64}, content)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="require size"):
        skill_catalog._resource_digest_and_size({}, None)  # noqa: SLF001

    with pytest.raises(skill_catalog.InvalidSkillError, match="per-skill size"):
        skill_catalog._resource_entry(
            {"uri": uri, "size": skill_catalog.MAX_SKILL_BYTES + 1, "sha256": "0" * 64},
            skill={},
            candidate={},
            skill_uri=uri,
            first=True,
        )  # noqa: SLF001


def test_resource_collections_require_a_static_root_and_unique_bounded_entries():
    uri = _skill_uri()
    root = skill_catalog._skill_root(uri)  # noqa: SLF001
    resource = _resource(uri)
    assert skill_catalog._resource_entries("dynamic", skill={}, candidate={}, skill_uri=uri) == "dynamic"  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="non-empty"):
        skill_catalog._resource_entries(None, skill={}, candidate={}, skill_uri=uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="non-empty"):
        skill_catalog._resource_entries([], skill={}, candidate={}, skill_uri=uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="non-empty"):
        skill_catalog._resource_entries(
            [resource] * (skill_catalog.MAX_RESOURCES_PER_SKILL + 1), skill={}, candidate={}, skill_uri=uri
        )  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="objects"):
        skill_catalog._resource_entries(["not an object"], skill={}, candidate={}, skill_uri=uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="more than once"):
        skill_catalog._resource_entries([resource, resource], skill={}, candidate={}, skill_uri=uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="include the root"):
        skill_catalog._resource_entries([_resource(f"{root}/references/api.md")], skill={}, candidate={}, skill_uri=uri)  # noqa: SLF001
    with pytest.raises(skill_catalog.InvalidSkillError, match="total size"):
        skill_catalog._resource_entries(
            [
                resource,
                {"uri": f"{root}/large.bin", "size": skill_catalog.MAX_SKILL_BYTES, "sha256": "0" * 64},
            ],
            skill={},
            candidate={},
            skill_uri=uri,
        )  # noqa: SLF001


def test_candidate_shapes_and_frontmatter_precedence_are_supported():
    candidate = _skill_candidate()
    assert skill_catalog._candidate_skill_payload(candidate)["name"] == "lookup"  # noqa: SLF001
    plain = {"name": "plain"}
    assert skill_catalog._candidate_skill_payload(plain) is plain  # noqa: SLF001
    assert skill_catalog._candidate_list({"name": "one"}) == [{"name": "one"}]  # noqa: SLF001
    assert skill_catalog._candidate_list([{"name": "one"}, "skip"]) == [{"name": "one"}]  # noqa: SLF001
    assert skill_catalog._candidate_list(None) == []  # noqa: SLF001

    explicit_skill = {"frontmatter": {"name": "skill"}}
    explicit_candidate = {"frontmatter": {"name": "candidate"}}
    assert skill_catalog._candidate_frontmatter(explicit_skill, explicit_candidate, {}) == {"name": "skill"}  # noqa: SLF001
    assert skill_catalog._candidate_frontmatter({}, explicit_candidate, {}) == {"name": "candidate"}  # noqa: SLF001
    fallback = skill_catalog._candidate_frontmatter(
        {"baz": "skill"}, {"bar": "candidate", "skill": {}, "resources": []}, {"foo": "record"}
    )  # noqa: SLF001
    assert fallback == {"foo": "record", "bar": "candidate", "baz": "skill"}

    source = {"id": "record-source"}
    artifacts = [{"name": "artifact", "source": {"id": "artifact-source"}}, "skip"]
    pairs = skill_catalog._candidate_records({"source": source, "artifacts": artifacts})  # noqa: SLF001
    assert pairs == [(artifacts[0], {"id": "artifact-source"})]
    assert len(skill_catalog._candidate_records({"skills": {"name": "one"}})) == 1  # noqa: SLF001
    assert len(skill_catalog._candidate_records({"skill": {"name": "one"}})) == 1  # noqa: SLF001
    assert len(skill_catalog._candidate_records({"evolved": {"skills": {"name": "one"}}})) == 1  # noqa: SLF001
    assert len(skill_catalog._candidate_records({"evolved": {"skill": {"name": "one"}}})) == 1  # noqa: SLF001
    assert len(skill_catalog._candidate_records({"tool_type": " SKILL "})) == 1  # noqa: SLF001
    assert skill_catalog._candidate_records({}) == []  # noqa: SLF001


def test_entries_reject_invalid_candidates_and_use_nested_evolved_metadata():
    candidate = _skill_candidate(extra_field={"kept": True})
    entry = skill_catalog._entry_from_candidate(candidate, {}, {})  # noqa: SLF001
    assert entry.frontmatter["name"] == "lookup"
    assert entry.catalog_metadata == {"extra_field": {"kept": True}}

    nested = _skill_candidate()["skill"]
    nested["evolved"] = {"mcp": {"resource_uri": _skill_uri()}}
    nested_candidate = {"tool_type": "skill", "skill": nested}
    assert skill_catalog._entry_from_candidate(nested_candidate, {}, {}).evolved["mcp"]  # noqa: SLF001

    record_evolved = {"mcp": {"resource_uri": _skill_uri()}}
    record_candidate = {"tool_type": "skill", "skill": {**nested, "evolved": {}}}
    entry = skill_catalog._entry_from_candidate(record_candidate, {}, {"evolved": record_evolved})  # noqa: SLF001
    assert entry.evolved == record_evolved

    with pytest.raises(skill_catalog.InvalidSkillError, match="name and description"):
        skill_catalog._entry_from_candidate(  # noqa: SLF001
            {"tool_type": "skill", "skill": {"resources": "dynamic"}}, {}, {}
        )

    assert skill_catalog._entries_from_record(None) == []  # noqa: SLF001
    assert skill_catalog._entries_from_record({"skills": [{"tool_type": "web app"}]}) == []  # noqa: SLF001
    assert skill_catalog._entries_from_record({"skills": [{"tool_type": "skill", "skill": {}}]}) == []  # noqa: SLF001


def test_dynamic_resources_are_excluded_from_resource_listing(monkeypatch):
    uri = _skill_uri()
    dynamic = skill_catalog.SkillEntry(uri, {}, "dynamic", "", {}, {}, {})
    resource = skill_catalog.SkillResource(uri, "SKILL.md", "text/markdown", 1, "sha256:" + "a" * 64, b"x")
    static = skill_catalog.SkillEntry(uri, {}, (resource,), "", {}, {}, {})
    monkeypatch.setattr(skill_catalog, "all_entries", lambda: [dynamic, static])

    assert skill_catalog.resource_entries() == [(static, resource)]
    assert skill_catalog.find_skill(uri) is dynamic
    assert skill_catalog.find_resource(uri) == (static, resource)
