# SPDX-License-Identifier: GPL-3.0-or-later
"""Stateless streamable-HTTP MCP endpoint behavior."""

import hashlib
import json
from datetime import timedelta

import pytest
from flask import Flask

import backend
from backend import db, security, v1_facets
from backend.models import CanonicalToolCache, CatalogFacetValue, SourceAnalysisReport, User, utcnow
from backend.sync import REVIEW_APPROVED


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    # The facet-values cache is per-process with a 15-minute TTL; without
    # this, tests here can be served values computed from a previous test
    # module's discarded in-memory DB (order-dependent flake).
    v1_facets.clear_cache()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _facet(s, tool, field, value, label, bp):
    """Seed a facet row the way catalog_projection writes them."""
    s.add(
        CatalogFacetValue(
            tool_name=tool,
            field=field,
            value=value.casefold(),
            label=label,
            provenance=[{"source": "repository_analysis"}],
            confidence_basis_points=bp,
            refreshed_at=utcnow(),
        )
    )


def _seed(s):
    """Two canonical tools, two analysis reports, facets for both.

    SourceAnalysisReport.user_id is NOT NULL (models.py:1061); seed a user
    first (pattern: tests/proxy/test_graph_enrichment.py:72-79).
    """
    user = User(wm_sub="42", username="Seeder")
    s.add(user)
    s.flush()
    s.add(SourceAnalysisReport(tool_name="sfedits", report={}, user_id=user.id, review_status=REVIEW_APPROVED))
    s.add(SourceAnalysisReport(tool_name="cite-checker", report={}, user_id=user.id, review_status=REVIEW_APPROVED))
    for name, title, description in (
        ("sfedits", "SF edits", "San Francisco edit stream bot"),
        ("cite-checker", "Cite checker", "checks citations for accuracy"),
    ):
        s.add(
            CanonicalToolCache(
                tool_name=name,
                record={"name": name, "title": title, "description": description},
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )
    _facet(s, "sfedits", "dependency", "pypi:pywikibot", "pywikibot (pypi)", 9500)
    _facet(s, "sfedits", "wikimedia_api", "wikidata-query-service", "Wikidata Query Service", 9400)
    _facet(s, "sfedits", "detected_technology", "python", "Python", 9400)
    _facet(s, "sfedits", "technology", "python", "Python (declared)", 10000)
    _facet(s, "cite-checker", "dependency", "pypi:pywikibot", "pywikibot (pypi)", 8000)


def _skill_record():
    """One repository record containing two independently addressable skills."""
    source = {
        "id": "github:example/skill-repository",
        "repository": "https://github.com/example/skill-repository",
        "ref": "main",
        "commit": "abc123",
        "base_path": "skills/",
    }

    def resource(path, uri, content, mime_type="text/markdown"):
        body = content.encode("utf-8")
        return {
            "path": path,
            "uri": uri,
            "mime_type": mime_type,
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            # Inline bytes model the local resource cache. The public manifest
            # never exposes this field; resources/read serves it lazily.
            "content": content,
        }

    return {
        "name": "skill-repository",
        "title": "Repository skills",
        "source": source,
        "skills": [
            {
                "tool_type": "skill",
                "id": "github:example/skill-repository#skills/lookup",
                "name": "lookup",
                "description": "Look up Wikimedia project data.",
                "projects": ["enwiki", "wikidatawiki"],
                "skill": {
                    "root": "skills/lookup",
                    "entrypoint": "SKILL.md",
                    "frontmatter": {
                        "name": "lookup",
                        "description": "Look up Wikimedia project data.",
                        "projects": ["enwiki", "wikidatawiki"],
                        "license": "GPL-3.0-or-later",
                    },
                    "resources": [
                        resource(
                            "skills/lookup/SKILL.md",
                            "skill://toolhub-evolved/catalog/lookup/SKILL.md",
                            "# Lookup\n\nUse the catalog.\n",
                        ),
                        resource(
                            "skills/lookup/references/api.md",
                            "skill://toolhub-evolved/catalog/lookup/references/api.md",
                            "# API reference\n",
                        ),
                    ],
                },
                "evolved": {
                    "visibility": "public",
                    "review_status": "approved",
                    "mcp": {"resource_uri": "skill://toolhub-evolved/catalog/lookup/SKILL.md"},
                },
            },
            {
                "tool_type": "skill",
                "id": "github:example/skill-repository#skills/summarize",
                "name": "summarize",
                "description": "Summarize a Wikimedia project report.",
                "skill": {
                    "root": "skills/summarize",
                    "entrypoint": "SKILL.md",
                    "frontmatter": {
                        "name": "summarize",
                        "description": "Summarize a Wikimedia project report.",
                    },
                    "resources": [
                        resource(
                            "skills/summarize/SKILL.md",
                            "skill://toolhub-evolved/catalog/summarize/SKILL.md",
                            "# Summarize\n",
                        )
                    ],
                },
                "evolved": {
                    "visibility": "public",
                    "review_status": "approved",
                    "mcp": {"resource_uri": "skill://toolhub-evolved/catalog/summarize/SKILL.md"},
                },
            },
        ],
    }


def test_mcp_rate_limiter_trips_and_clears():
    security.clear_rate_limits()
    assert not security.mcp_rate_limited("10.0.0.1")
    for _ in range(security.MCP_LIMIT_PER_WINDOW):
        security.mcp_rate_limited("10.0.0.1")
    assert security.mcp_rate_limited("10.0.0.1")
    assert not security.mcp_rate_limited("10.0.0.2")
    security.clear_rate_limits()
    assert not security.mcp_rate_limited("10.0.0.1")


def _rpc(client, method, params=None, req_id=1, headers=None):
    body = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers or {})


def test_legacy_initialize_and_ping(client):
    resp = _rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    )
    assert resp.status_code == 200
    assert "Mcp-Session-Id" not in resp.headers
    data = resp.get_json()
    assert data["jsonrpc"] == "2.0" and data["id"] == 1
    result = data["result"]
    assert result["protocolVersion"] == "2025-06-18"  # echoed when supported
    assert "tools" in result["capabilities"] and "prompts" in result["capabilities"]
    assert result["serverInfo"]["name"] == "toolhub-evolved"
    unknown = _rpc(client, "initialize", {"protocolVersion": "1999-01-01"}).get_json()
    assert unknown["result"]["protocolVersion"] == "2025-11-25"  # our newest legacy
    assert _rpc(client, "ping").get_json()["result"] == {}


def test_server_discover(client):
    result = _rpc(client, "server/discover").get_json()["result"]
    assert result["protocolVersion"] == "2026-07-28"
    assert result["resultType"] == "complete"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "toolhub-evolved"


def test_notifications_get_202(client):
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202
    assert resp.get_data() == b""


def test_protocol_errors(client):
    parse = client.post("/mcp", data="{not json", content_type="application/json")
    assert parse.get_json()["error"]["code"] == -32700
    assert _rpc(client, "no/such/method").get_json()["error"]["code"] == -32601
    not_request = client.post("/mcp", json={"hello": "world"})
    assert not_request.get_json()["error"]["code"] == -32600
    batch = client.post("/mcp", json=[{"jsonrpc": "2.0", "method": "ping", "id": 1}])
    assert batch.status_code == 400
    assert batch.get_json()["error"]["code"] == -32600
    assert client.get("/mcp").status_code == 405


def test_origin_validation(client):
    # No Origin (CLI / server-side MCP clients): allowed.
    assert _rpc(client, "ping").status_code == 200
    # Same-origin browser calls: allowed.
    ok = _rpc(client, "ping", headers={"Origin": "https://toolhub-evolved.toolforge.org"})
    assert ok.status_code == 200
    # Any other browser origin: DNS-rebinding defense, 403.
    bad = _rpc(client, "ping", headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403


def test_rate_limited_mcp(client, monkeypatch):
    monkeypatch.setattr(security, "mcp_rate_limited", lambda addr: True)
    assert _rpc(client, "ping").status_code == 429


def _call_tool(client, name, arguments):
    return _rpc(client, "tools/call", {"name": name, "arguments": arguments}).get_json()


def test_tools_list_shapes(client):
    result = _rpc(client, "tools/list").get_json()["result"]
    assert result["resultType"] == "complete"
    assert result["cacheScope"] == "public"
    assert result["ttlMs"] > 0
    tools = result["tools"]
    assert [t["name"] for t in tools] == [
        "search_tools",
        "facet_tools",
        "list_facet_values",
        "get_tool",
    ]  # deterministic order per spec
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_skill_capabilities_are_additive(client):
    initialized = _rpc(client, "initialize", {"protocolVersion": "2025-06-18"}).get_json()["result"]
    assert initialized["capabilities"]["resources"] == {"subscribe": False, "listChanged": False}
    assert initialized["capabilities"]["extensions"]["io.modelcontextprotocol/skills"] == {
        "directoryRead": False
    }
    discovered = _rpc(client, "server/discover").get_json()["result"]
    assert discovered["capabilities"]["resources"] == {"subscribe": False, "listChanged": False}
    assert "io.modelcontextprotocol/skills" in discovered["capabilities"]["extensions"]
    # The existing tools surface remains exactly the four catalog tools.
    assert [tool["name"] for tool in _rpc(client, "tools/list").get_json()["result"]["tools"]] == [
        "search_tools",
        "facet_tools",
        "list_facet_values",
        "get_tool",
    ]


def test_skills_list_keeps_multiple_skills_from_one_repository(client):
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="skill-repository",
                record=_skill_record(),
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )

    result = _rpc(client, "skills/list").get_json()["result"]
    assert result["resultType"] == "complete"
    assert [skill["frontmatter"]["name"] for skill in result["skills"]] == ["lookup", "summarize"]
    lookup = result["skills"][0]
    assert lookup["uri"] == "skill://toolhub-evolved/catalog/lookup/SKILL.md"
    assert [resource["uri"] for resource in lookup["resources"]] == [
        "skill://toolhub-evolved/catalog/lookup/SKILL.md",
        "skill://toolhub-evolved/catalog/lookup/references/api.md",
    ]
    assert lookup["resources"][0]["size"] == len("# Lookup\n\nUse the catalog.\n".encode("utf-8"))
    assert "content" not in lookup["resources"][0]
    assert lookup["frontmatter"]["projects"] == ["enwiki", "wikidatawiki"]
    assert lookup["_meta"]["io.modelcontextprotocol/skills/evolved"]["review_status"] == "approved"
    assert lookup["_meta"]["io.modelcontextprotocol/skills/source"]["commit"] == "abc123"
    assert lookup["_meta"]["io.modelcontextprotocol/skills/catalog"]["projects"] == ["enwiki", "wikidatawiki"]


def test_evolved_catalog_artifacts_and_skill_pagination_are_supported(client):
    record = _skill_record()
    evolved_catalog = {
        "_schema": "/toolinfo/evolved/1.0.0",
        "type": "evolved-catalog",
        "source": record["source"],
        "artifacts": record["skills"],
    }
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="evolved-skill-catalog",
                record=evolved_catalog,
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )

    first = _rpc(client, "skills/list", {"limit": 1}).get_json()["result"]
    assert [skill["frontmatter"]["name"] for skill in first["skills"]] == ["lookup"]
    assert first["nextCursor"] == "1"
    assert first["skills"][0]["_meta"]["io.modelcontextprotocol/skills/artifactId"].endswith("#skills/lookup")
    second = _rpc(client, "skills/list", {"cursor": first["nextCursor"], "limit": 1}).get_json()["result"]
    assert [skill["frontmatter"]["name"] for skill in second["skills"]] == ["summarize"]
    assert "nextCursor" not in second


def test_skill_uri_generation_preserves_repository_path_and_object_shape(client):
    skill = _skill_record()["skills"][0]
    for resource in skill["skill"]["resources"]:
        resource.pop("uri")
    skill["evolved"]["mcp"].pop("resource_uri")
    record = {
        "name": "object-shaped-skill-repository",
        "source": {
            "id": "github:example/object-shaped-skill-repository",
            "repository": "https://github.com/example/object-shaped-skill-repository",
        },
        # Accept the single-skill spelling as well as the multi-skill array.
        "skills": skill,
    }
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="object-shaped-skill-repository",
                record=record,
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )

    result = _rpc(client, "skills/list").get_json()["result"]
    assert [entry["frontmatter"]["name"] for entry in result["skills"]] == ["lookup"]
    uri = result["skills"][0]["uri"]
    assert uri == "skill://toolhub-evolved/catalog/github/example/object-shaped-skill-repository/skills/lookup/SKILL.md"
    assert result["skills"][0]["resources"][0]["uri"] == uri


def test_skills_get_and_resources_read_are_lazy(client):
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="skill-repository",
                record=_skill_record(),
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )

    uri = "skill://toolhub-evolved/catalog/lookup/SKILL.md"
    skill = _rpc(client, "skills/get", {"uri": uri}).get_json()["result"]["skill"]
    assert skill["uri"] == uri
    assert skill["frontmatter"]["name"] == "lookup"
    assert skill["resources"][0]["digest"].startswith("sha256:")

    listed = _rpc(client, "resources/list").get_json()["result"]["resources"]
    assert [resource["uri"] for resource in listed] == [
        "skill://toolhub-evolved/catalog/lookup/SKILL.md",
        "skill://toolhub-evolved/catalog/lookup/references/api.md",
        "skill://toolhub-evolved/catalog/summarize/SKILL.md",
    ]
    read = _rpc(client, "resources/read", {"uri": uri}).get_json()["result"]
    assert read["contents"] == [
        {"uri": uri, "mimeType": "text/markdown", "text": "# Lookup\n\nUse the catalog.\n"}
    ]

    assert _rpc(client, "skills/get", {"uri": "skill://toolhub-evolved/catalog/missing/SKILL.md"}).get_json()[
        "error"
    ]["code"] == -32602
    assert _rpc(client, "resources/read", {"uri": "skill://toolhub-evolved/catalog/missing.txt"}).get_json()[
        "error"
    ]["code"] == -32602


def test_skill_pagination_parameter_edges_and_binary_resource(client, monkeypatch):
    assert _rpc(client, "skills/list", {"cursor": "not-a-number"}).get_json()["error"]["code"] == -32602
    assert _rpc(client, "skills/list", {"cursor": -1}).get_json()["error"]["code"] == -32602
    assert _rpc(client, "skills/list", {"limit": "not-a-number"}).status_code == 200
    assert _rpc(client, "skills/get", {"uri": ""}).get_json()["error"]["code"] == -32602
    assert _rpc(client, "resources/read", {"uri": ""}).get_json()["error"]["code"] == -32602

    from backend import mcp_server

    uri = "skill://toolhub-evolved/catalog/binary/references/icon.bin"
    resource = mcp_server.skill_catalog.SkillResource(
        uri,
        "icon.bin",
        "application/octet-stream",
        2,
        "sha256:" + "a" * 64,
        b"\xff\x00",
    )
    entry = mcp_server.skill_catalog.SkillEntry(uri, {}, (resource,), "", {}, {}, {})
    monkeypatch.setattr(
        mcp_server.skill_catalog,
        "find_resource",
        lambda candidate: (entry, resource) if candidate == uri else None,
    )

    result = _rpc(client, "resources/read", {"uri": uri}).get_json()["result"]
    assert result["contents"] == [{"uri": uri, "mimeType": "application/octet-stream", "blob": "/wA="}]


def test_manifest_without_cached_body_stays_discoverable_but_not_readable(client):
    record = _skill_record()
    for skill in record["skills"]:
        for resource in skill["skill"]["resources"]:
            resource.pop("content")
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="metadata-only-skill-repository",
                record=record,
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )
    uri = "skill://toolhub-evolved/catalog/lookup/SKILL.md"
    assert _rpc(client, "skills/get", {"uri": uri}).get_json()["result"]["skill"]["frontmatter"]["name"] == "lookup"
    error = _rpc(client, "resources/read", {"uri": uri}).get_json()["error"]
    assert error["code"] == -32602
    assert "not available" in error["message"]


def test_malformed_skill_manifest_is_not_served(client):
    record = _skill_record()
    record["skills"][0]["skill"]["resources"][0]["sha256"] = "0" * 64
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="invalid-skill-repository",
                record=record,
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )
    result = _rpc(client, "skills/list").get_json()["result"]
    assert [skill["frontmatter"]["name"] for skill in result["skills"]] == ["summarize"]


def test_search_tools_call(client):
    with db.session_scope() as s:
        _seed(s)
    data = _call_tool(client, "search_tools", {"query": "citations", "limit": 5})
    result = data["result"]
    assert result["resultType"] == "complete"
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["tools"][0]["name"] == "cite-checker"
    assert payload["returned"] == 1
    assert "total" not in payload  # a capped page must not masquerade as a total
    assert result["structuredContent"] == payload  # additive 2026-07-28 field


def test_get_mcp_points_browser_visitors_to_documentation(client):
    response = client.get("/mcp")
    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"
    assert response.get_json() == {
        "error": "this endpoint speaks MCP over POST and offers no SSE stream",
        "documentation": "/mcp-server",
    }


def test_facet_tools_schema_advertises_purpose_filters(client):
    """An LLM can only use filters it can see in the schema."""
    tools = _rpc(client, "tools/list").get_json()["result"]["tools"]
    facet = next(t for t in tools if t["name"] == "facet_tools")
    props = set(facet["inputSchema"]["properties"])
    assert {"task", "audience"} <= props
    # Every server-side filter param must be advertised, or it is unusable.
    from backend import v1_facets

    assert set(v1_facets.FILTER_PARAMS) <= props
    assert {"technology", "detected_technology", "declared_technology", "ui_language"} <= props
    assert facet["inputSchema"]["properties"]["technology"]["deprecated"] is True


def test_search_tools_uses_local_replica_when_upstream_is_down(client, monkeypatch):
    from backend import toolhub

    def boom(path, params=None):
        raise AssertionError("public MCP search must not contact upstream")

    monkeypatch.setattr(toolhub, "public_api_get", boom)
    with db.session_scope() as s:
        _seed(s)
    result = _call_tool(client, "search_tools", {"query": "citations"})["result"]
    assert result.get("isError") is not True
    payload = json.loads(result["content"][0]["text"])
    assert [tool["name"] for tool in payload["tools"]] == ["cite-checker"]


def test_facet_tools_call_includes_coverage(client):
    with db.session_scope() as s:
        _seed(s)
    payload = json.loads(
        _call_tool(client, "facet_tools", {"dependency": ["pywikibot"]})["result"]["content"][0]["text"]
    )
    assert {t["name"] for t in payload["tools"]} == {"cite-checker", "sfedits"}
    assert payload["coverage"] == {"scannedTools": 2, "totalTools": 2}


def test_list_facet_values_and_get_tool(client):
    with db.session_scope() as s:
        _seed(s)
    values = json.loads(_call_tool(client, "list_facet_values", {"type": "dependency"})["result"]["content"][0]["text"])
    assert values["values"][0]["value"] == "pypi:pywikibot"
    assert "coverage" in values
    tool = json.loads(_call_tool(client, "get_tool", {"name": "sfedits"})["result"]["content"][0]["text"])
    assert tool["record"]["title"] == "SF edits"


def test_mcp_facet_names_preserve_technology_compatibility(client):
    with db.session_scope() as s:
        _seed(s)

    legacy = json.loads(
        _call_tool(client, "facet_tools", {"technology": ["python"]})["result"]["content"][0]["text"]
    )
    canonical = json.loads(
        _call_tool(client, "facet_tools", {"detected_technology": ["python"]})["result"]["content"][0]["text"]
    )
    declared = json.loads(
        _call_tool(client, "facet_tools", {"declared_technology": ["python"]})["result"]["content"][0]["text"]
    )
    assert legacy["total"] == canonical["total"] == declared["total"] == 1
    assert canonical["tools"][0]["matched"][0]["facet"] == "detected_technology"
    assert declared["tools"][0]["matched"][0]["facet"] == "declared_technology"

    listed = json.loads(
        _call_tool(client, "list_facet_values", {"type": "api"})["result"]["content"][0]["text"]
    )
    assert listed["type"] == "api"


def test_facet_tools_limit_never_exceeds_serializer_cap(client):
    """Clamped limit + true total: no husk records past MAX_QUERY_NAMES."""
    from backend import canonical_tools as ct

    with db.session_scope() as s:
        user = User(wm_sub="43", username="BulkSeeder")
        s.add(user)
        s.flush()
        for i in range(ct.MAX_QUERY_NAMES + 5):
            name = f"tool-{i:03d}"
            s.add(
                CanonicalToolCache(
                    tool_name=name,
                    record={"name": name, "title": f"Tool {i}"},
                    expires_at=utcnow() + timedelta(hours=1),
                    stale_until=utcnow() + timedelta(hours=2),
                )
            )
            s.add(SourceAnalysisReport(tool_name=name, report={}, user_id=user.id, review_status=REVIEW_APPROVED))
            _facet(s, name, "dependency", "pypi:pywikibot", "pywikibot (pypi)", 9000)
    payload = json.loads(
        _call_tool(client, "facet_tools", {"dependency": ["pywikibot"], "limit": 9999})["result"]["content"][0]["text"]
    )
    assert len(payload["tools"]) <= ct.MAX_QUERY_NAMES
    assert all(t["title"] for t in payload["tools"])  # no husk records
    assert payload["total"] == ct.MAX_QUERY_NAMES + 5  # true total, not page size


def test_facet_tools_scalar_filter_is_not_dropped(client):
    """A bare string where the schema says array must still filter."""
    with db.session_scope() as s:
        _seed(s)
    # Scalar alone works like the single-item list it stands for.
    alone = _call_tool(client, "facet_tools", {"dependency": "pywikibot"})["result"]
    assert alone["isError"] is False
    assert json.loads(alone["content"][0]["text"])["total"] == 2
    # Scalar combined with another filter must narrow the AND, not vanish.
    combined = _call_tool(client, "facet_tools", {"technology": "rust", "dependency": ["pywikibot"]})["result"]
    assert combined["isError"] is False
    payload = json.loads(combined["content"][0]["text"])
    assert payload["tools"] == [] and payload["total"] == 0


def test_tool_argument_edge_cases_error_or_fall_back(client):
    """Blank required args error; a malformed limit falls back to the default."""
    with db.session_scope() as s:
        _seed(s)
    no_filters = _call_tool(client, "facet_tools", {})["result"]
    assert no_filters["isError"] is True
    assert "at least one filter" in no_filters["content"][0]["text"]
    bad_limit = _call_tool(client, "facet_tools", {"dependency": ["pywikibot"], "limit": "abc"})["result"]
    assert bad_limit["isError"] is False
    assert json.loads(bad_limit["content"][0]["text"])["total"] == 2
    blank_query = _call_tool(client, "search_tools", {"query": "   "})["result"]
    assert blank_query["isError"] is True
    blank_name = _call_tool(client, "get_tool", {"name": "   "})["result"]
    assert blank_name["isError"] is True


def test_facet_tools_unknown_value_matches_nothing(client):
    with db.session_scope() as s:
        _seed(s)
    result = _call_tool(client, "facet_tools", {"dependency": ["nosuchpkg"], "api": ["wikidata-query-service"]})[
        "result"
    ]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    # Unknown dependency + valid API filter: empty, never widened to API-only.
    assert payload["tools"] == [] and payload["total"] == 0


def test_tool_call_errors(client):
    assert _call_tool(client, "nope", {})["error"]["code"] == -32602
    bad = _call_tool(client, "list_facet_values", {"type": "bogus"})["result"]
    assert bad["isError"] is True
    assert "dependency" in bad["content"][0]["text"]  # names the valid types
    missing = _call_tool(client, "get_tool", {"name": "not-a-tool"})["result"]
    assert missing["isError"] is True


def test_unexpected_handler_failure_returns_jsonrpc_error(client, monkeypatch):
    """A crashing handler must yield -32603, never Flask's HTML 500 page."""
    from backend import mcp_server

    def boom(_arguments):
        msg = "db went away"
        raise RuntimeError(msg)

    monkeypatch.setitem(mcp_server._TOOL_HANDLERS, "get_tool", boom)
    response = _rpc(client, "tools/call", {"name": "get_tool", "arguments": {"name": "x"}})
    assert response.status_code == 200
    body = response.get_json()
    assert body["error"]["code"] == -32603
    assert "db went away" not in body["error"]["message"]  # no internals leaked


def test_prompts_list_and_get(client):
    result = _rpc(client, "prompts/list").get_json()["result"]
    assert result["resultType"] == "complete"
    assert result["cacheScope"] == "public"
    prompts = result["prompts"]
    assert prompts[0]["name"] == "prior-art-review"
    assert prompts[0]["arguments"][0] == {
        "name": "project_description",
        "description": "The greenfield tool idea, in a sentence or three",
        "required": True,
    }
    got = _rpc(
        client,
        "prompts/get",
        {
            "name": "prior-art-review",
            "arguments": {"project_description": "a bot that fixes broken citations on enwiki"},
        },
    ).get_json()["result"]
    assert got["resultType"] == "complete"
    text_out = got["messages"][0]["content"]["text"]
    assert "a bot that fixes broken citations on enwiki" in text_out
    assert "search_tools" in text_out and "facet_tools" in text_out
    assert "coverage" in text_out  # the caveat instruction ships with the prompt
    assert _rpc(client, "prompts/get", {"name": "missing"}).get_json()["error"]["code"] == -32602
    no_arg = _rpc(client, "prompts/get", {"name": "prior-art-review"}).get_json()
    assert no_arg["error"]["code"] == -32602
