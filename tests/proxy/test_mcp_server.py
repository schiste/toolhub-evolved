# SPDX-License-Identifier: GPL-3.0-or-later
"""Stateless streamable-HTTP MCP endpoint behavior."""

import json
from datetime import timedelta

import pytest
from flask import Flask

import backend
from backend import db, security, tool_facets, v1_facets
from backend.models import CanonicalToolCache, CatalogFacetValue, SourceAnalysisReport, User, utcnow
from backend.sync import REVIEW_APPROVED


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
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
    _facet(s, "cite-checker", "dependency", "pypi:pywikibot", "pywikibot (pypi)", 8000)


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
    resp = _rpc(client, "initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    })
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
        "search_tools", "facet_tools", "list_facet_values", "get_tool",
    ]  # deterministic order per spec
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_search_tools_call(client, monkeypatch):
    from backend import toolhub

    # Stub upstream search to return controlled data
    def stub_search(path, params=None):
        if params and params.get("q") == "citations":
            return {"results": [{"name": "cite-checker"}]}
        return {"results": []}

    monkeypatch.setattr(toolhub, "public_api_get", stub_search)
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


def test_facet_tools_schema_advertises_purpose_filters(client):
    """An LLM can only use filters it can see in the schema."""
    tools = _rpc(client, "tools/list").get_json()["result"]["tools"]
    facet = next(t for t in tools if t["name"] == "facet_tools")
    props = set(facet["inputSchema"]["properties"])
    assert {"task", "audience"} <= props
    # Every server-side filter param must be advertised, or it is unusable.
    from backend import v1_facets

    assert set(v1_facets.FILTER_PARAMS) <= props


def test_search_tools_fails_loudly_when_upstream_is_down(client, monkeypatch):
    """No local fallback: a weak answer is worse than none for prior art.

    Substring-matching the local cache would quietly under-report existing
    tools, and the caller acts on that by building something that already
    exists - the exact failure this product prevents. Stub the pure upstream
    boundary so the production handler still runs.
    """
    import requests

    from backend import toolhub

    def boom(path, params=None):
        raise requests.RequestException("upstream unreachable")

    monkeypatch.setattr(toolhub, "public_api_get", boom)
    with db.session_scope() as s:
        _seed(s)
    result = _call_tool(client, "search_tools", {"query": "citations"})["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"].casefold()
    assert "unavailable" in text and "retry" in text
    # Must NOT have silently degraded to local results.
    assert "cite-checker" not in text


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
    values = json.loads(
        _call_tool(client, "list_facet_values", {"type": "dependency"})["result"]["content"][0]["text"]
    )
    assert values["values"][0]["value"] == "pypi:pywikibot"
    assert "coverage" in values
    tool = json.loads(_call_tool(client, "get_tool", {"name": "sfedits"})["result"]["content"][0]["text"])
    assert tool["record"]["title"] == "SF edits"


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


def test_facet_tools_unknown_value_matches_nothing(client):
    with db.session_scope() as s:
        _seed(s)
    result = _call_tool(
        client, "facet_tools", {"dependency": ["nosuchpkg"], "api": ["wikidata-query-service"]}
    )["result"]
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
    got = _rpc(client, "prompts/get", {
        "name": "prior-art-review",
        "arguments": {"project_description": "a bot that fixes broken citations on enwiki"},
    }).get_json()["result"]
    assert got["resultType"] == "complete"
    text_out = got["messages"][0]["content"]["text"]
    assert "a bot that fixes broken citations on enwiki" in text_out
    assert "search_tools" in text_out and "facet_tools" in text_out
    assert "coverage" in text_out  # the caveat instruction ships with the prompt
    assert _rpc(client, "prompts/get", {"name": "missing"}).get_json()["error"]["code"] == -32602
    no_arg = _rpc(client, "prompts/get", {"name": "prior-art-review"}).get_json()
    assert no_arg["error"]["code"] == -32602
