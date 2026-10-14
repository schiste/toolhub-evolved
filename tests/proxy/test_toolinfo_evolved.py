# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the additive Toolhub Evolved artifact extension."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import skill_catalog, skill_discovery, toolinfo_extension  # noqa: E402
from backend.models import CanonicalToolCache, catalog_card_record  # noqa: E402

REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def _canonical_record(name: str, evolved: dict | None = None) -> dict:
    record = {
        "_schema": "/toolinfo/1.2.2",
        "name": name,
        "title": name,
        "description": f"Record for {name}.",
        "url": "https://example.org/tools/" + name,
        "tool_type": "other",
    }
    if evolved is not None:
        record["evolved"] = evolved
    return record


def _extension(artifact_type: str, **payload: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "artifact_type": artifact_type,
        "artifact_id": f"test:{artifact_type}/one",
        "source": {
            "id": "github:example/one",
            "repository": "https://github.com/example/one",
            "commit": REVISION,
        },
        "revision": REVISION,
        "content_sha256": DIGEST,
        "provenance": {"source_kind": "repository_scan", "run_id": "scan-42", "commit": REVISION},
        "visibility": "private",
        "review_status": "pending",
        "analysis": {
            "reference": "source-analysis:scan-42",
            "revision": REVISION,
            "content_sha256": DIGEST,
            "status": "pending",
        },
        **payload,
    }


def _skill_extension() -> dict:
    return _extension(
        "skill",
        skill={
            "root": "skills/lookup",
            "entrypoint": "SKILL.md",
            "frontmatter": {"name": "lookup", "description": "Find a page."},
            "resources": [
                {
                    "path": "skills/lookup/SKILL.md",
                    "mime_type": "text/markdown",
                    "size": 0,
                    "sha256": "b" * 64,
                }
            ],
        },
    )


def _mcp_extension() -> dict:
    return _extension(
        "mcp_server",
        mcp_server={
            "name": "example-server",
            "transport": "stdio",
            "package": "npm:@example/mcp-server@1.0.0",
            "protocol_version": "2025-03-26",
            "capabilities": ["tools"],
            "authentication": {"required": True, "methods": ["oauth2"], "permissions": ["read:pages"]},
        },
    )


def test_canonical_and_evolved_validators_accept_base_enriched_and_mixed_records():
    canonical = _canonical_record("canonical-only")
    skill = _canonical_record("evolved-skill", _skill_extension())
    mcp_server = _canonical_record("evolved-mcp", _mcp_extension())
    mixed = [canonical, skill, mcp_server]

    for document in (canonical, skill, mcp_server, mixed):
        toolinfo_extension.validate_canonical_document(document)
        toolinfo_extension.validate_toolinfo_document(document)

    cached = CanonicalToolCache(tool_name=skill["name"], record=skill)
    assert cached.record["evolved"]["artifact_type"] == "skill"
    assert "evolved" not in catalog_card_record(skill)


def test_mcp_descriptor_supports_http_but_rejects_credentials_and_transport_mismatch():
    http_record = _canonical_record("http-mcp", _mcp_extension())
    server = http_record["evolved"]["mcp_server"]
    server["transport"] = "streamable-http"
    server.pop("package")
    server["endpoint"] = "https://mcp.example.org/mcp"
    toolinfo_extension.validate_toolinfo_document(http_record)

    credential_record = _canonical_record("credential-mcp", _mcp_extension())
    credential_record["evolved"]["mcp_server"]["access_token"] = "[REDACTED]"
    with pytest.raises(toolinfo_extension.ToolinfoValidationError):
        toolinfo_extension.validate_toolinfo_document(credential_record)

    credential_endpoint = _canonical_record("credential-endpoint", _mcp_extension())
    credential_endpoint["evolved"]["mcp_server"]["endpoint"] = "https://user:[REDACTED]@mcp.example.org/mcp"
    credential_endpoint["evolved"]["mcp_server"]["transport"] = "streamable-http"
    credential_endpoint["evolved"]["mcp_server"].pop("package")
    with pytest.raises(toolinfo_extension.ToolinfoValidationError):
        toolinfo_extension.validate_toolinfo_document(credential_endpoint)

    credential_package = _canonical_record("credential-package", _mcp_extension())
    credential_package["evolved"]["mcp_server"]["transport"] = "stdio"
    credential_package["evolved"]["mcp_server"]["package"] = "https://user:[REDACTED]@registry.example/mcp"
    with pytest.raises(toolinfo_extension.ToolinfoValidationError):
        toolinfo_extension.validate_toolinfo_document(credential_package)

    missing_endpoint = _canonical_record("missing-endpoint", _mcp_extension())
    missing_endpoint["evolved"]["mcp_server"]["transport"] = "streamable-http"
    with pytest.raises(toolinfo_extension.ToolinfoValidationError):
        toolinfo_extension.validate_toolinfo_document(missing_endpoint)


def test_user_script_has_its_own_typed_payload():
    record = _canonical_record(
        "user-script",
        _extension(
            "user_script",
            user_script={
                "wiki": "en.wikipedia.org",
                "page_title": "User:Example/common.js",
                "source_url": "https://en.wikipedia.org/wiki/User:Example/common.js",
            },
        ),
    )
    toolinfo_extension.validate_toolinfo_document(record)


def test_extension_requires_matching_immutable_revision_and_type_payload():
    mismatched = _canonical_record("bad-analysis", _skill_extension())
    mismatched["evolved"]["analysis"]["revision"] = "different-revision"
    with pytest.raises(toolinfo_extension.ToolinfoValidationError, match="analysis.*revision"):
        toolinfo_extension.validate_toolinfo_document(mismatched)

    mismatched_digest = _canonical_record("bad-digest", _skill_extension())
    mismatched_digest["evolved"]["analysis"]["content_sha256"] = "sha256:" + "c" * 64
    with pytest.raises(toolinfo_extension.ToolinfoValidationError, match="analysis.*digest"):
        toolinfo_extension.validate_toolinfo_document(mismatched_digest)

    wrong_payload = _canonical_record("wrong-payload", _skill_extension())
    wrong_payload["evolved"]["mcp_server"] = _mcp_extension()["mcp_server"]
    with pytest.raises(toolinfo_extension.ToolinfoValidationError):
        toolinfo_extension.validate_toolinfo_document(wrong_payload)

    invalid_canonical_enum = _canonical_record("bad-tool-type", _skill_extension())
    invalid_canonical_enum["tool_type"] = "skill"
    with pytest.raises(toolinfo_extension.ToolinfoValidationError, match="tool_type"):
        toolinfo_extension.validate_toolinfo_document(invalid_canonical_enum)


def test_repository_discovery_emits_canonical_skill_records_and_skill_reader_consumes_them():
    result = skill_discovery.discover_catalog(
        [{
            "path": "skills/lookup/SKILL.md",
            "content": "---\nname: lookup\ndescription: Find a page.\n---\n# Lookup\n",
        }],
        {"id": "github:example/skills", "repository": "https://github.com/example/skills"},
        run_id="scan-42",
        commit=REVISION,
    )

    assert isinstance(result.catalog, list)
    assert result.discovered == 1
    record = result.catalog[0]
    assert record["_schema"] == "/toolinfo/1.2.2"
    assert {"name", "title", "description", "url"} <= set(record)
    assert record.get("tool_type") in {None, "web app", "desktop app", "bot", "gadget", "user script", "command line tool", "coding framework", "lua module", "template", "other"}
    assert record["evolved"]["artifact_type"] == "skill"
    assert record["evolved"]["skill"]["entrypoint"] == "SKILL.md"
    toolinfo_extension.validate_toolinfo_document(result.catalog)
    entry = skill_catalog._entries_from_record(record)[0]
    assert entry.artifact_id == record["evolved"]["artifact_id"]
    assert entry.frontmatter["name"] == "lookup"

    mcp_record = _canonical_record("mcp-only", _mcp_extension())
    assert skill_catalog._entries_from_record(mcp_record) == []
