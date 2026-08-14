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

import requests
from flask import Blueprint, Response, jsonify, request

from backend import canonical_tools, db, security, toolhub, v1_facets
from backend import tool_facets as facets_backend

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

# The serializer truncates at canonical_tools.MAX_QUERY_NAMES (=50 today,
# canonical_tools.py:23,294); exceeding it yields husk records with empty
# titles, so both the clamp and the advertised schema maxima derive from it.
_MAX_TOOL_RESULTS = canonical_tools.MAX_QUERY_NAMES


class _ParamError(ValueError):
    """Handler-raised for malformed params; mapped to -32602."""


class _ToolError(ValueError):
    """Tool-execution failure surfaced to the calling LLM via isError."""


def _error(req_id: Any, code: int, message: str, status: int = 200) -> tuple[Response, int]:  # noqa: ANN401
    return (
        jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}),
        status,
    )


def _result(req_id: Any, result: dict[str, Any]) -> Response:  # noqa: ANN401
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


_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "search_tools",
        "description": (
            "Relevance-ranked search over all ~4,500 Wikimedia tools in the Toolhub "
            "catalog, served by Toolhub's own search index. Covers the full catalog. "
            "Keep queries SHORT and distinctive (2-3 content words): terms are matched "
            "independently and scored, so extra common words ('wikipedia', 'check', "
            "'tool') pull in unrelated results and push good ones down. Prefer several "
            "narrow queries with different vocabulary over one long descriptive one. "
            "If this tool reports search is unavailable, say so plainly rather than "
            "substituting weaker evidence - facet_tools and get_tool still work."
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
            "tool_type (e.g. 'bot', 'web app'), keyword, wiki, license, and — for what a "
            "tool is FOR rather than what it is built from — task and audience. Those two "
            "are only filled in for a small minority of tools, so use them to narrow a "
            "search, never to conclude that nothing does a thing."
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
                "task": {"type": "array", "items": {"type": "string"}},
                "audience": {"type": "array", "items": {"type": "string"}},
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
    """Idea-similarity search, delegated to upstream Toolhub.

    Upstream is Elasticsearch-backed and handles the sentence-shaped queries
    an LLM composes ("find unsourced statements needing references"); the
    local canonical search is substring matching and cannot. public_api_get
    carries the compliant User-Agent and the shared ApiCache (same path as
    catalog_sync.py:292). Falls back to the local cache only when upstream
    is unavailable, and says so in the payload so the caller can caveat it.
    """
    query = str(arguments.get("query") or "").strip()
    if not query:
        msg = "query must be a non-empty string"
        raise _ToolError(msg)
    limit = _limit_from(arguments, 10)
    try:
        payload = toolhub.public_api_get("/api/search/tools/", params={"q": query, "page_size": limit})
    except (OSError, requests.RequestException, toolhub.ToolhubAPIError) as exc:
        # Deliberately no local fallback. canonical_tools.search is substring
        # matching ordered by cache-fetch time; for prior art a weak answer is
        # WORSE than none, because the caller acts on it and builds a tool that
        # already exists. Fail loudly so the report says "search unavailable"
        # instead of silently under-reporting. facet_tools and get_tool are
        # unaffected - they read local data and still work.
        msg = f"Toolhub search is unavailable right now ({exc}); retry shortly"
        raise _ToolError(msg) from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    names = [str(r.get("name")) for r in (results or []) if isinstance(r, dict) and r.get("name")]
    # "returned", not "total": a capped page labeled "total" reads as
    # "only N tools exist" to an LLM.
    return {"tools": v1_facets.tool_summaries(names, matched_by_tool={}), "returned": len(names)}


def _tool_facet_tools(arguments: dict[str, Any]) -> dict[str, Any]:
    with db.session_scope() as s:
        filters: dict[str, list[str]] = {}
        for param, facet_type in v1_facets.FILTER_PARAMS.items():
            raw_values = arguments.get(param)
            if raw_values is None:
                continue
            if not isinstance(raw_values, list):
                # LLM callers routinely send a bare string where the schema
                # says array. Wrap it instead of dropping the filter — a
                # dropped filter silently widens the AND, the one failure
                # mode this surface must never have.
                raw_values = [raw_values]
            requested = sorted({str(v).strip().casefold() for v in raw_values if str(v).strip()})
            if not requested:
                continue
            values = v1_facets.dependency_values(s, requested) if facet_type == "dependency" else requested
            # Same rule as the REST route: an unknown value is a filter that
            # matches nothing, not an invalid request — and the Phase 1
            # helpers treat the resulting empty list as matching nothing
            # rather than dropping it (which would widen the AND).
            filters[facet_type] = sorted({str(v).strip().casefold() for v in values if str(v).strip()})
        if not filters:
            msg = (
                "supply at least one filter: dependency, api, technology (detected), "
                "or tool_type, keyword, wiki, license (declared)"
            )
            raise _ToolError(msg)
        matches = facets_backend.tools_matching_facets(s, filters, limit=_limit_from(arguments, 25))
        total = facets_backend.count_matching(s, filters)
        disclosed = v1_facets.coverage(s)
    matched_by_tool = {m.tool_name: m.matched for m in matches}
    return {
        "tools": v1_facets.tool_summaries([m.tool_name for m in matches], matched_by_tool=matched_by_tool),
        "total": total,
        "coverage": disclosed,
    }


def _tool_list_facet_values(arguments: dict[str, Any]) -> dict[str, Any]:
    facet_type = str(arguments.get("type") or "").strip().casefold()
    if facet_type not in set(v1_facets.FILTER_PARAMS.values()):
        valid_types = ", ".join(sorted(set(v1_facets.FILTER_PARAMS.values())))
        msg = f"type must be one of: {valid_types}"
        raise _ToolError(msg)
    # Through the same cached accessor as the REST route (Phase 3 Task 3) —
    # this tool is the fan-out surface the cache exists for.
    listing = v1_facets.cached_facet_values(facet_type, limit=facets_backend.DEFAULT_VALUE_RESULTS)
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
        msg = "name must be a non-empty string"
        raise _ToolError(msg)
    records = canonical_tools.tools_by_name([name])
    if name not in records:
        msg = f"no canonical tool named {name!r}; names are exact and case-sensitive"
        raise _ToolError(msg)
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
        msg = f"unknown tool: {name}"
        raise _ParamError(msg)
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


def _validate_mcp_request() -> tuple[dict[str, Any], str, Any] | tuple[Response, int, None]:
    """Validate an MCP request and return (body, method, req_id) or error response."""
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return _error(None, INVALID_REQUEST, "origin not allowed", status=403), None, None
    if security.mcp_rate_limited(request.remote_addr):
        return _error(None, -32000, "rate limited, retry later", status=429), None, None
    try:
        body = request.get_json(force=True)
    except Exception:  # noqa: BLE001 - any unparseable body is the same protocol error
        return _error(None, PARSE_ERROR, "request body is not valid JSON"), None, None
    if isinstance(body, list):
        return _error(None, INVALID_REQUEST, "batch requests are not supported", status=400), None, None
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not body.get("method"):
        return _error(None, INVALID_REQUEST, "expected a JSON-RPC 2.0 request object"), None, None
    method = str(body["method"])
    req_id = body.get("id")
    return body, method, req_id


@mcp_bp.route("/mcp", methods=["POST"])
def mcp_endpoint() -> Response | tuple[Response, int]:
    """Dispatch one self-contained JSON-RPC request."""
    result = _validate_mcp_request()
    if result[1] is None:  # Validation error
        return result[0]  # type: ignore[return-value]
    body, method, req_id = result
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    if method.startswith("notifications/"):
        return Response(status=202)
    handler = _METHODS.get(method)
    if handler is None:
        return _error(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")
    try:
        return _result(req_id, handler(params))
    except _ParamError as exc:
        return _error(req_id, INVALID_PARAMS, str(exc))


_PRIOR_ART_PROMPT = (
    "You are evaluating a greenfield tool idea for the Wikimedia ecosystem.\n\n"
    "## The Idea\n\n"
    "{project_description}\n\n"
    "## Your task\n\n"
    "Determine whether this idea already exists as a tool in Wikimedia's ecosystem, "
    "whether it is too similar to existing tools to justify, or whether it is "
    "genuinely novel and differentiated.\n\n"
    "You have three catalog-discovery tools available:\n\n"
    "1. **search_tools(query, limit=10)**: Relevance-ranked search across the full "
    "~4,500-tool catalog. Keep queries short and distinctive (2-3 content words); "
    "longer queries introduce noise. Prefer several narrow queries with different "
    "vocabulary.\n\n"
    "2. **facet_tools(dependency=[], api=[], technology=[], tool_type=[], keyword=[], "
    "wiki=[], license=[], limit=25)**: Find tools by technical signals (detected "
    "dependency packages and APIs used) or catalog metadata (declared types, keywords, "
    "wikis, licenses). Check the returned `coverage` field — an empty result may "
    "reflect limited catalog scanning, not absence of tools.\n\n"
    "3. **list_facet_values(type)**: List adoption-ranked values of a facet type "
    "before calling facet_tools. Supported types: dependency, wikimedia_api, "
    "detected_technology (detected in scanned repos), tool_type, keywords, wiki, "
    "license (declared metadata).\n\n"
    "## Methodology\n\n"
    "1. **Characterize** your idea in 2-3 alternate phrasings, predicting:\n"
    "   - Likely Wikimedia APIs it would call (mediawiki-action-api, wikibase-api, "
    "wikidata-query-service, mediawiki-rest-api, toolforge, commons-upload) or "
    '"none"\n'
    "   - Likely technology/language (python, javascript, php, etc.)\n"
    "   - Likely tool_type (bot, gadget, web app, library, etc.)\n\n"
    "2. **Retrieve** across both methods:\n"
    "   - Call **search_tools** once per phrasing (3+ calls if you have 3+ phrasings)\n"
    "   - Inspect `facet_tools` with filters for the predicted API, technology, and "
    "tool_type\n"
    "   - Call `list_facet_values` first if you don't know what values exist for a "
    "facet type\n\n"
    "3. **Report** in three sections:\n"
    "   - **Build / Reuse / Differentiate**: Name the closest existing tool(s), "
    "explain specific ways the idea is novel or an improvement, or confirm it "
    "duplicates an existing tool.\n"
    "   - **Adjacent Tools**: List other tools (from the same search/facet queries) "
    "that might be dependencies, reference implementations, or alternatives.\n"
    "   - **Recommended Stack** (if novel): Name adopted packages, libraries, or "
    "frameworks you found via facet_tools, ranked by how many tools already use them "
    "(the facet_tools response includes adoption counts).\n\n"
    "Always restate the `coverage` numbers returned by facet_tools. If no scanned "
    "tool matches your predicted facet filters, phrase it as 'no scanned tool matches "
    "[filter]' rather than implying absence from the full catalog.\n\n"
    "## Start now\n\n"
    "Apply the methodology above. Report your findings in the three sections. Cite "
    "tool names and specific evidence."
)


_PROMPT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "prior-art-review",
        "description": "Prior-art review for a greenfield Wikimedia tool idea",
        "arguments": [
            {
                "name": "project_description",
                "description": "The greenfield tool idea, in a sentence or three",
                "required": True,
            }
        ],
    },
)


def _prompts_list(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultType": "complete",
        "prompts": list(_PROMPT_DEFINITIONS),
        "ttlMs": LIST_TTL_MS,
        "cacheScope": "public",
    }


def _prompts_get(params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    prompt_def = next((p for p in _PROMPT_DEFINITIONS if p["name"] == name), None)
    if prompt_def is None:
        msg = f"unknown prompt: {name}"
        raise _ParamError(msg)
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    for arg in prompt_def.get("arguments", []):
        if arg.get("required") and arg["name"] not in arguments:
            msg = f"required argument missing: {arg['name']}"
            raise _ParamError(msg)
    description = arguments.get("project_description", "")
    return {
        "resultType": "complete",
        "description": prompt_def["description"],
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": _PRIOR_ART_PROMPT.format(project_description=description)},
            }
        ],
    }


_METHODS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "initialize": _initialize,
    "server/discover": _server_discover,
    "ping": lambda _params: {},
    "tools/list": _tools_list,
    "tools/call": _tools_call,
    "prompts/list": _prompts_list,
    "prompts/get": _prompts_get,
}
