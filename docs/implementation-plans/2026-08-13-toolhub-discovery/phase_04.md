# Toolhub Discovery Implementation Plan — Phase 4: MCP Server

> **For Claude:** REQUIRED SUB-SKILL: Use ed3d-plan-and-execute:executing-an-implementation-plan to implement this plan task-by-task.

**Goal:** Any MCP-capable client can add `https://toolhub-evolved.toolforge.org/mcp` and get four catalog tools plus a `prior-art-review` prompt.

**Architecture:** Native Flask implementation of stateless streamable-HTTP MCP (single `POST /mcp` JSON-RPC 2.0 endpoint, plain JSON responses, no SSE, no sessions) in a new `proxy/backend/mcp_server.py` blueprint. **Decision recorded:** the official MCP Python SDK v2 emits ASGI apps only; Toolforge's `webservice` runs uWSGI (WSGI), so using the SDK would mean a second service or converting the whole app to ASGI — disproportionate for four read-only tools. Rate limiting reuses the repo's own `security.py` rolling-window pattern and depends on Phase 3's ProxyFix task for real client addresses.

**Tech Stack:** Flask 3, JSON-RPC 2.0 per the MCP spec (pinned below), pytest via Flask `test_client`, `@modelcontextprotocol/inspector` for conformance.

**Scope:** Phase 4 of 5 from `docs/design-plans/2026-08-13-toolhub-discovery.md`. Depends on Phases 1-3 (including Phase 3 Task 3's ProxyFix and `security.py` additions).

**Codebase verified:** 2026-08-13. **MCP spec researched and pinned:** 2026-08-13.

---

## Pinned protocol facts (researched 2026-08-13, spec revision 2026-07-28)

The current spec revision is **2026-07-28** (https://modelcontextprotocol.io/specification/2026-07-28) and it is a **breaking, fully-stateless revision**: `initialize`/`notifications/initialized` and `ping` are REMOVED, replaced by a `server/discover` method; every request instead carries `_meta` with namespaced keys (`io.modelcontextprotocol/protocolVersion`, `.../clientCapabilities`); list results gain `resultType: "complete"`, `ttlMs`, and `cacheScope`; JSON-RPC batching is gone (reject top-level arrays with 400); servers MUST NOT issue `Mcp-Session-Id`; GET on the endpoint → 405.

Because that revision is two weeks old, essentially all deployed clients (including current Claude clients) still speak the **legacy revisions 2025-03-26 / 2025-06-18 / 2025-11-25** with the `initialize` handshake — which is also stateless-compatible (a server that never issues `Mcp-Session-Id` is a valid stateless server there). Therefore this endpoint speaks BOTH, which is cheap because the tools/prompts method shapes are identical across revisions and the new response fields are additive (legacy clients ignore unknown fields):

| Concern | Behavior |
| --- | --- |
| `initialize` (legacy) | Answer with negotiated legacy `protocolVersion`, `capabilities: {tools: {}, prompts: {}}`, `serverInfo`. Never issue `Mcp-Session-Id`. |
| `notifications/*` | 202, empty body. |
| `ping` (legacy) | `{}`. |
| `server/discover` (2026-07-28) | `protocolVersion: "2026-07-28"`, `capabilities: {tools: {"listChanged": false}, prompts: {"listChanged": false}}`, `serverInfo`, `resultType: "complete"`. |
| `tools/list`, `tools/call`, `prompts/list`, `prompts/get` | One handler each, shared across revisions; responses carry the additive 2026-07-28 fields (`resultType`, `ttlMs`, `cacheScope` on lists; `resultType` + `structuredContent` on calls). |
| `_meta` / protocol-version negotiation | Lenient acceptance: missing `_meta` (legacy clients) is fine; an unknown declared version is served anyway with our fields — rejecting would break older/newer minor clients for no protective benefit on a read-only server. |
| `MCP-Protocol-Version` HTTP header | If present and recognized, fine; if present and unrecognized, still serve (log at debug). Strict rejection is for stateful servers guarding session semantics we don't have. |
| `Origin` header | **MUST validate** (DNS-rebinding defense, both revisions). Policy for this public read-only API: requests without `Origin` (CLI/server-side clients, including Claude) are allowed; any browser `Origin` not in the allowlist (default: the tool's own origin) → 403. |
| Top-level JSON array (legacy batch) | 400 with a JSON-RPC `-32600` error object. |
| GET/DELETE `/mcp` | 405. |
| Error codes | -32700 parse, -32600 invalid request, -32601 method not found, -32602 invalid params (including unknown tool/prompt names). |

Conformance is independently checked with `npx @modelcontextprotocol/inspector --cli` (Task 5), not only with our own test client.

---

### Task 1: MCP rate limiter in `security.py`

**Files:**
- Modify: `proxy/backend/security.py`
- Test: `tests/proxy/test_mcp_server.py` (create; limiter test only for now)

**Step 1: Read `security.py` lines 60-140** for the limiter class and module-function idiom (Phase 3 Task 3 already added a second instance — mirror it).

**Step 2: Write the failing test**

Create `tests/proxy/test_mcp_server.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stateless streamable-HTTP MCP endpoint behavior."""

import json
from datetime import timedelta

import pytest
from flask import Flask

import backend
from backend import db, security, tool_facets, v1_facets
from backend.models import CanonicalToolCache, SourceAnalysisReport, User, utcnow


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


def _seed(s):
    """Two canonical tools, two analysis reports, facets for both.

    SourceAnalysisReport.user_id is NOT NULL (models.py:1061); seed a user
    first (pattern: tests/proxy/test_graph_enrichment.py:72-79).
    """
    user = User(wm_sub="42", username="Seeder")
    s.add(user)
    s.flush()
    s.add(SourceAnalysisReport(tool_name="sfedits", report={}, user_id=user.id))
    s.add(SourceAnalysisReport(tool_name="cite-checker", report={}, user_id=user.id))
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
    tool_facets.replace_analyzer_facets(
        s,
        "sfedits",
        {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.95}],
         "apis": [{"value": "wikidata-query-service", "confidence": 0.94}]},
        source_report_id=1,
    )
    tool_facets.replace_analyzer_facets(
        s,
        "cite-checker",
        {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.8}]},
        source_report_id=2,
    )


def test_mcp_rate_limiter_trips_and_clears():
    security.clear_rate_limits()
    assert not security.mcp_rate_limited("10.0.0.1")
    for _ in range(security.MCP_LIMIT_PER_WINDOW):
        security.mcp_rate_limited("10.0.0.1")
    assert security.mcp_rate_limited("10.0.0.1")
    assert not security.mcp_rate_limited("10.0.0.2")
    security.clear_rate_limits()
    assert not security.mcp_rate_limited("10.0.0.1")
```

**Step 3: Run to verify failure** (`AttributeError: mcp_rate_limited`), then implement in `security.py`: `MCP_LIMIT_PER_WINDOW = 60`, a limiter instance beside the existing ones, `def mcp_rate_limited(client_addr: str | None) -> bool` mirroring `read_rate_limited` (line 130), and registration in `clear_rate_limits()`.

**Step 4: Run test** — PASS.

**Step 5: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/security.py tests/proxy/test_mcp_server.py
git commit -m "feat: rate-limit the MCP endpoint"
```

---

### Task 2: JSON-RPC envelope, transport rules, and lifecycle methods

**Files:**
- Create: `proxy/backend/mcp_server.py`
- Modify: `proxy/backend/__init__.py` (register blueprint beside the v1 blueprints)
- Test: `tests/proxy/test_mcp_server.py` (extend)

**Step 1: Write the failing tests**

```python
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
```

**Step 2: Run to verify failure** — 404 on `/mcp`.

**Step 3: Implement**

Create `proxy/backend/mcp_server.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stateless streamable-HTTP MCP endpoint for catalog discovery.

Implements the Model Context Protocol directly as one JSON-RPC 2.0 POST
endpoint returning plain JSON. Native Flask rather than the official MCP SDK:
the SDK emits ASGI apps and this service runs under Toolforge's WSGI
webservice, so the SDK would force a second deployable.

Speaks both the 2026-07-28 stateless revision (server/discover, _meta) and
the legacy initialize-handshake revisions still used by deployed clients;
the tools/prompts method shapes are identical across them and the newer
response fields are additive. No sessions are ever issued, which is valid
stateless behavior in every supported revision.
"""

import json
from collections.abc import Callable
from typing import Any

from flask import Blueprint, Response, jsonify, request

from backend import security

mcp_bp = Blueprint("mcp", __name__)

SERVER_INFO = {"name": "toolhub-evolved", "version": "1.0.0"}
CURRENT_PROTOCOL_VERSION = "2026-07-28"
# Legacy initialize-handshake revisions this endpoint accepts; newest first.
# The subset of the protocol used here (tools + prompts over streamable HTTP,
# plain JSON, no sessions) is wire-identical across them.
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
# MCP negotiation guidance: when the client's requested version is unknown,
# answer with the newest we support.
DEFAULT_LEGACY_VERSION = LEGACY_PROTOCOL_VERSIONS[0]
# Browser origins allowed to call the endpoint. Programmatic MCP clients send
# no Origin header and are always allowed; anything else is DNS-rebinding
# surface and gets 403 (spec: servers MUST validate Origin).
ALLOWED_ORIGINS = frozenset({"https://toolhub-evolved.toolforge.org"})
# Freshness hints for 2026-07-28 list caching; the catalog changes on the
# 15-minute sync cadence, so half that keeps clients comfortably current.
LIST_TTL_MS = 7 * 60 * 1000

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class _ParamError(ValueError):
    """Handler-raised for malformed params; mapped to -32602."""


class _ToolError(ValueError):
    """Tool-execution failure surfaced to the calling LLM via isError."""


def _error(req_id: Any, code: int, message: str, status: int = 200) -> tuple[Response, int]:
    return (
        jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}),
        status,
    )


def _result(req_id: Any, result: dict[str, Any]) -> Response:
    return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = str(params.get("protocolVersion") or "")
    negotiated = requested if requested in LEGACY_PROTOCOL_VERSIONS else DEFAULT_LEGACY_VERSION
    return {
        "protocolVersion": negotiated,
        "capabilities": {"tools": {}, "prompts": {}},
        "serverInfo": SERVER_INFO,
    }


def _server_discover(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultType": "complete",
        "protocolVersion": CURRENT_PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
    }


@mcp_bp.route("/mcp", methods=["POST"])
def mcp_endpoint() -> Response | tuple[Response, int]:
    """Dispatch one self-contained JSON-RPC request."""
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return _error(None, INVALID_REQUEST, "origin not allowed", status=403)
    if security.mcp_rate_limited(request.remote_addr):
        return _error(None, -32000, "rate limited, retry later", status=429)
    try:
        body = request.get_json(force=True)
    except Exception:  # noqa: BLE001 - any unparseable body is the same protocol error
        return _error(None, PARSE_ERROR, "request body is not valid JSON")
    if isinstance(body, list):
        # JSON-RPC batching was removed from the protocol; reject explicitly.
        return _error(None, INVALID_REQUEST, "batch requests are not supported", status=400)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not body.get("method"):
        return _error(None, INVALID_REQUEST, "expected a JSON-RPC 2.0 request object")
    method = str(body["method"])
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    req_id = body.get("id")
    if method.startswith("notifications/"):
        return Response(status=202)
    handler = _METHODS.get(method)
    if handler is None:
        return _error(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")
    try:
        return _result(req_id, handler(params))
    except _ParamError as exc:
        return _error(req_id, INVALID_PARAMS, str(exc))


_METHODS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "initialize": _initialize,
    "server/discover": _server_discover,
    "ping": lambda _params: {},
}
```

Register `mcp_bp` in `proxy/backend/__init__.py` beside the v1 blueprints.

**Step 4: Run tests** — PASS (GET 405 comes free from `methods=["POST"]`).

**Step 5: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/mcp_server.py proxy/backend/__init__.py tests/proxy/test_mcp_server.py
git commit -m "feat: add dual-revision stateless MCP endpoint"
```

---

### Task 3: The four tools

**Files:**
- Modify: `proxy/backend/mcp_server.py`
- Test: `tests/proxy/test_mcp_server.py` (extend; `_seed` is already local to this file)

**Step 1: Write the failing tests**

```python
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
            s.add(SourceAnalysisReport(tool_name=name, report={}, user_id=user.id))
            tool_facets.replace_analyzer_facets(
                s, name, {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.9}]},
                source_report_id=i + 10,
            )
    payload = json.loads(
        _call_tool(client, "facet_tools", {"dependency": ["pywikibot"], "limit": 9999})["result"]["content"][0]["text"]
    )
    assert len(payload["tools"]) <= ct.MAX_QUERY_NAMES
    assert all(t["title"] for t in payload["tools"])  # no husk records
    assert payload["total"] == ct.MAX_QUERY_NAMES + 5  # true total, not page size


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
```

**Step 2: Run to verify failure**, then implement in `mcp_server.py`. Complete code — definitions, handlers, and dispatch:

```python
from backend import canonical_tools, db, v1_facets
from backend import tool_facets as facets_backend
from backend.models import FACET_TYPES

# The serializer truncates at canonical_tools.MAX_QUERY_NAMES (=50 today,
# canonical_tools.py:23,294); exceeding it yields husk records with empty
# titles, so both the clamp and the advertised schema maxima derive from it.
_MAX_TOOL_RESULTS = canonical_tools.MAX_QUERY_NAMES

_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "search_tools",
        "description": (
            "Relevance-ranked full-text search over all ~4,500 Wikimedia tools in the "
            "Toolhub catalog (titles, descriptions, keywords). Use several phrasings for "
            "concept searches; results cover the full catalog."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_TOOL_RESULTS, "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "facet_tools",
        "description": (
            "Find tools by verified technical signals extracted from their source code: "
            "dependency (package name, optionally ecosystem-prefixed like 'pypi:pywikibot'), "
            "api (one of: mediawiki-action-api, wikibase-api, wikidata-query-service, "
            "mediawiki-rest-api, toolforge, commons-upload), technology (a language detected "
            "in the source, e.g. 'python'). Filters AND together. These three are DETECTED "
            "from source code, so they cover only tools with a scanned repository — check the "
            "returned coverage field; an empty result is not proof that no such tool exists. "
            "You can also filter on DECLARED catalog metadata, which covers every tool: "
            "tool_type (e.g. 'bot', 'web app'), keyword, wiki, license."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependency": {"type": "array", "items": {"type": "string"}},
                "api": {"type": "array", "items": {"type": "string"}},
                "technology": {"type": "array", "items": {"type": "string"}},
                "tool_type": {"type": "array", "items": {"type": "string"}},
                "keyword": {"type": "array", "items": {"type": "string"}},
                "wiki": {"type": "array", "items": {"type": "string"}},
                "license": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_TOOL_RESULTS, "default": 25},
            },
        },
    },
    {
        "name": "list_facet_values",
        "description": (
            "List the distinct values of one facet type ranked by how many tools carry "
            "each — the ecosystem's actual adoption ranking. Call before facet_tools to "
            "learn what values exist. Detected types (scanned repos only): dependency, "
            "wikimedia_api, detected_technology. Declared types (whole catalog): tool_type, "
            "keywords, wiki, license. The response says which family a type belongs to."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"type": {"type": "string"}},
            "required": ["type"],
        },
    },
    {
        "name": "get_tool",
        "description": "Fetch one tool's full canonical Toolhub record by exact tool name.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
)


def _limit_from(arguments: dict[str, Any], default: int) -> int:
    try:
        return max(1, min(_MAX_TOOL_RESULTS, int(arguments.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _tool_search_tools(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise _ToolError("query must be a non-empty string")
    results = canonical_tools.search(query, limit=_limit_from(arguments, 10))
    names = [payload["toolName"] for payload in results]
    # "returned", not "total": search has no cheap true-total and a capped
    # page labeled "total" reads as "only N tools exist" to an LLM.
    return {"tools": v1_facets.tool_summaries(names, matched_by_tool={}), "returned": len(names)}


def _tool_facet_tools(arguments: dict[str, Any]) -> dict[str, Any]:
    with db.session_scope() as s:
        filters: dict[str, list[str]] = {}
        declared: dict[str, list[str]] = {}
        for param, field in v1_facets.DECLARED_FILTER_PARAMS.items():
            raw_values = arguments.get(param)
            if not isinstance(raw_values, list):
                continue
            requested = sorted({str(v).strip().casefold() for v in raw_values if str(v).strip()})
            if requested:
                declared[field] = requested
        for param, facet_type in v1_facets.FILTER_PARAMS.items():
            raw_values = arguments.get(param)
            if not isinstance(raw_values, list):
                continue
            requested = sorted({str(v).strip().casefold() for v in raw_values if str(v).strip()})
            if not requested:
                continue
            values = (
                v1_facets.dependency_values(s, requested)
                if facet_type == "dependency"
                else requested
            )
            # Same rule as the REST route: an unknown value is a filter that
            # matches nothing, not an invalid request — and the Phase 1
            # helpers treat the resulting empty list as matching nothing
            # rather than dropping it (which would widen the AND).
            filters[facet_type] = sorted(
                {str(v).strip().casefold() for v in values if str(v).strip()}
            )
        if not filters and not declared:
            raise _ToolError(
                "supply at least one filter: dependency, api, technology (detected), "
                "or tool_type, keyword, wiki, license (declared)"
            )
        matches = facets_backend.tools_matching_facets(
            s, filters, declared_filters=declared, limit=_limit_from(arguments, 25)
        )
        total = facets_backend.count_matching(s, filters, declared_filters=declared)
        disclosed = v1_facets.coverage(s)
    matched_by_tool = {m.tool_name: m.matched for m in matches}
    return {
        "tools": v1_facets.tool_summaries(
            [m.tool_name for m in matches], matched_by_tool=matched_by_tool
        ),
        "total": total,
        "coverage": disclosed,
    }


def _tool_list_facet_values(arguments: dict[str, Any]) -> dict[str, Any]:
    facet_type = str(arguments.get("type") or "").strip().casefold()
    if facet_type not in FACET_TYPES:
        raise _ToolError(f"type must be one of: {', '.join(sorted(FACET_TYPES))}")
    # Through the same cached accessor as the REST route (Phase 3 Task 3) —
    # this tool is the fan-out surface the cache exists for.
    listing = v1_facets.cached_facet_values(
        facet_type, limit=facets_backend.DEFAULT_VALUE_RESULTS
    )
    with db.session_scope() as s:
        disclosed = v1_facets.coverage(s)
    return {
        "type": facet_type,
        "values": listing["values"],
        "totalValues": listing["totalValues"],
        "coverage": disclosed,
    }


def _tool_get_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name") or "").strip()
    if not name:
        raise _ToolError("name must be a non-empty string")
    records = canonical_tools.tools_by_name([name])
    if name not in records:
        raise _ToolError(f"no canonical tool named {name!r}; names are exact and case-sensitive")
    return records[name]


_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "search_tools": _tool_search_tools,
    "facet_tools": _tool_facet_tools,
    "list_facet_values": _tool_list_facet_values,
    "get_tool": _tool_get_tool,
}


def _tools_list(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultType": "complete",
        "tools": list(_TOOL_DEFINITIONS),
        "ttlMs": LIST_TTL_MS,
        "cacheScope": "public",
    }


def _tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise _ParamError(f"unknown tool: {name}")
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    try:
        payload = handler(arguments)
    except _ToolError as exc:
        return {
            "resultType": "complete",
            "content": [{"type": "text", "text": str(exc)}],
            "isError": True,
        }
    return {
        "resultType": "complete",
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
        "isError": False,
    }


_METHODS.update({"tools/list": _tools_list, "tools/call": _tools_call})
```

(`v1_facets.dependency_values` and `v1_facets.cached_facet_values` are public names defined in Phase 3 for exactly this cross-surface reuse.) Consolidate all imports at the top of `mcp_server.py`.

`structuredContent` note: the spec permits it without a declared `outputSchema`; if the Task 5 inspector gate objects anyway, declare an `outputSchema` per tool (the payload shapes here are stable dicts) rather than dropping the field.

**Step 3: Run tests** — PASS; then full suite + coverage; add branch tests until the ratchet holds (limit clamping, empty arguments, non-dict arguments).

**Step 4: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/mcp_server.py proxy/backend/v1_facets.py tests/proxy/
git commit -m "feat: expose catalog discovery tools over MCP"
```

---

### Task 4: The `prior-art-review` prompt

**Files:**
- Modify: `proxy/backend/mcp_server.py`
- Test: `tests/proxy/test_mcp_server.py` (extend)

**Step 1: Failing tests**

```python
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
```

**Step 2: Implement.** `prompts/list` → `{"resultType": "complete", "prompts": [...], "ttlMs": LIST_TTL_MS, "cacheScope": "public"}` with the single prompt definition matching the test. `prompts/get` validates the name (else `_ParamError`) and the required argument (else `_ParamError`), then returns:

```python
{
    "resultType": "complete",
    "description": "Prior-art review for a greenfield Wikimedia tool idea",
    "messages": [
        {
            "role": "user",
            "content": {"type": "text", "text": _PRIOR_ART_PROMPT.format(project_description=description)},
        }
    ],
}
```

`_PRIOR_ART_PROMPT` is a module-level template constant containing the methodology (mirror the wording of `skills/toolhub-discovery/SKILL.md`, Phase 5 — the skill file is the canonical phrasing; keep the two aligned):

1. Characterize the idea ({project_description} interpolated at top): 2-3 alternate phrasings; predicted data access chosen from the six `api` values; likely technology and tool_type.
2. Retrieve twice: `search_tools` per phrasing; `list_facet_values` then `facet_tools` for the predicted pattern. Overlap between the two sets is the strongest signal.
3. Report in three sections (build/reuse/differentiate; adjacent tools; recommended stack ranked by adoption), citing tool names; flag deprecated tools rather than hiding them; always restate the returned `coverage` numbers and phrase facet absences as "no scanned tool matches."

Register both methods in `_METHODS`.

**Step 3: Run tests** — PASS; full suite + coverage.

**Step 4: Lint and commit**

```bash
git add proxy/backend/mcp_server.py tests/proxy/test_mcp_server.py
git commit -m "feat: ship the prior-art-review workflow as an MCP prompt"
```

---

### Task 5: Conformance check, documentation, deploy

**Files:**
- Modify: `docs/deploy-toolforge.md` (document `/mcp`; note `tools/deploy.sh` already runs `proxy/migrate.py` per `tools/deploy.sh:81`)
- Modify: `README.md` (short "MCP server" section: endpoint URL, `claude mcp add --transport http toolhub-discovery https://toolhub-evolved.toolforge.org/mcp`, the four tools, the prompt)
- Do NOT touch `docs/FEATURES.md` — it is generated from `public_html/views/experiments.js` by `tools/feature-docs.mjs`; backend-only changes need no edit there.

**Step 1: Local conformance gate (before docs).** Run the app locally (`README.md:108-135` dev-run steps) and exercise it with the official inspector — an independent client, not our own test helper:

```bash
npx @modelcontextprotocol/inspector --cli --transport http --method tools/list http://localhost:8000/mcp
npx @modelcontextprotocol/inspector --cli --transport http --method tools/call \
  --tool-name search_tools --tool-arg query=citation http://localhost:8000/mcp
npx @modelcontextprotocol/inspector --cli --transport http --method prompts/list http://localhost:8000/mcp
```

Expected: valid JSON-RPC results, tool list with all four tools. If the installed inspector speaks the 2026-07-28 revision it exercises the `server/discover` path; older inspector versions exercise the legacy `initialize` path — both must succeed. Fix any nonconformance it reveals before proceeding. (This is the design's "MCP SDK test client" done-when, satisfied with the reference client.)

**Step 2: Write the docs; run the prose checks** (`npx prettier --check .`, `npm run spell`); commit `docs: document the MCP discovery endpoint`.

**Step 3: Post-deploy verification (operator, not CI):** after the next Toolforge deploy — re-run the three inspector commands against `https://toolhub-evolved.toolforge.org/mcp`; `claude mcp add --transport http toolhub-discovery https://toolhub-evolved.toolforge.org/mcp` and, in a Claude session, list tools, call `search_tools` ("citation"), call `facet_tools` (`dependency: ["pywikibot"]`), fetch the `prior-art-review` prompt. Confirm `TOOLHUB_PROXYFIX_X_FOR` is set to the measured hop count (Phase 3) so the 429 burst check throttles one client, not everyone. Size the burst to the deployment: `RollingLimit` is per worker process (`security.py:66-68`), so with N uWSGI workers the effective ceiling is N × `MCP_LIMIT_PER_WINDOW` — burst well above that (e.g. 500 requests for 4 workers at 60/window) → 429; a second machine still gets 200s.

---

## Phase completion check

- Full MCP flow green in tests: legacy initialize AND server/discover → tools/list → tools/call (all four) → prompts/get, plus parse/batch/method/params/origin/rate-limit error paths.
- Inspector conformance commands succeed against a local server.
- Full suite + coverage ratchet green; ruff clean; prose checks green.
- Deviation ledger for the validator: native-Flask MCP (not the SDK) with dual-revision support — rationale in the module docstring; spec pinned 2026-08-13 in this file's header.
