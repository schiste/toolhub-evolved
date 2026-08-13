# Toolhub Discovery Implementation Plan — Phase 3: Facet REST Endpoints

> **For Claude:** REQUIRED SUB-SKILL: Use ed3d-plan-and-execute:executing-an-implementation-plan to implement this plan task-by-task.

**Goal:** "Which tools use X" answerable over public read-only HTTP: `GET /v1/facets/tools/` and `GET /v1/facets/values/`, both carrying coverage metadata.

**Architecture:** New `proxy/backend/v1_facets.py` blueprint following the `v1_statistics.py` module pattern, registered in `proxy/backend/__init__.py:91-110`. Query logic delegates to `tool_facets` helpers (Phase 1); tool summaries derive from `canonical_tools.tools_by_name` records so all discovery surfaces share one tool shape.

**Tech Stack:** Flask 3 blueprints, pytest via Flask `test_client` (pattern: `tests/proxy/test_backend.py:143-154`).

**Scope:** Phase 3 of 5 from `docs/design-plans/2026-08-13-toolhub-discovery.md`. Depends on Phase 1 (and benefits from Phase 2's keyword-rich records, but does not require it).

**Codebase verified:** 2026-08-13.

---

## Verified facts this phase relies on

- Blueprint pattern: `proxy/backend/v1_statistics.py:9` creates `Blueprint("v1_statistics", __name__)`; routes decorate with `@..._bp.route("/v1/...")`; `proxy/backend/__init__.py:91-110` registers each blueprint. Follow exactly.
- Canonical payloads come from `canonical_tools.tools_by_name(names)` → `{name: {"toolName", "record", ...}}` (`canonical_tools.py:270-301`). The canonical `record` holds `title`, `description`, `url`, `tool_type`, `repository`, `deprecated`, `keywords`.
- Total-tool count: count of `CanonicalToolCache` rows. Scanned-tool count: `tool_facets.scanned_tool_count(s)` (Phase 1).
- Facet vocabulary spans TWO tables (design decision 2026-08-13, see phase_01's Verified facts):
  - **Detected** (`ToolSignalFacet`, `FACET_TYPES` in `models.py`): `dependency`, `wikimedia_api`, `detected_technology` — analyzer-derived, only for tools with a scanned repo.
  - **Declared** (`CatalogFacetValue`, `catalog_projection.FACET_FIELDS`): `tool_type`, `keywords`, `wiki`, `technology`, `license`, `tasks`, `audiences`, `ui_language` — projected from the effective merged record, available for the whole catalog.
  `tool_facets.tools_matching_facets` / `count_matching` take `declared_filters=` for the second family (phase_01 Task 3b) and intersect both.
  **Coverage nuance this creates:** declared filters are NOT coverage-limited, detected ones are. A response's `coverage` block therefore describes only the detected side; say so rather than implying the whole query was coverage-limited.
- Response envelope conventions: see `/v1/canonical/tools/` (`v1.py:525-550`) — jsonify'd dict, camelCase keys for derived metadata.

---

### Task 1: Tool summary serializer + coverage helper

**Files:**
- Create: `proxy/backend/v1_facets.py` (serializer + coverage only; routes come in Task 2)
- Test: `tests/proxy/test_v1_facets.py` (create)

**Step 1: Write the failing tests**

Create `tests/proxy/test_v1_facets.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Facet discovery endpoints: tool lookup by signal, value listing, coverage."""

from datetime import timedelta

import pytest
from flask import Flask

import backend
from backend import db, security, tool_facets
from backend.models import CanonicalToolCache, utcnow


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _seed(s):
    # Coverage counts stored analysis reports, so seed those too.
    # SourceAnalysisReport.user_id is NOT NULL (models.py:1061) — same
    # seeding pattern as tests/proxy/test_graph_enrichment.py:72-79.
    from backend.models import SourceAnalysisReport, User

    user = User(wm_sub="42", username="Seeder")
    s.add(user)
    s.flush()
    s.add(SourceAnalysisReport(tool_name="sfedits", report={}, user_id=user.id))
    s.add(SourceAnalysisReport(tool_name="cite-checker", report={}, user_id=user.id))
    for name, record in (
        ("sfedits", {"name": "sfedits", "title": "SF edits", "description": "stream",
                     "url": "https://sfedits.example", "tool_type": "bot",
                     "repository": "https://github.com/tieguy/sfedits",
                     "keywords": ["edits"], "deprecated": False}),
        ("cite-checker", {"name": "cite-checker", "title": "Cite checker",
                          "description": "checks citations", "url": "https://c.example"}),
    ):
        s.add(
            CanonicalToolCache(
                tool_name=name,
                record=record,
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )
    tool_facets.replace_analyzer_facets(
        s,
        "sfedits",
        {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.95}],
         "apis": [{"value": "wikidata-query-service", "confidence": 0.94}],
         "technology": [{"value": "Python", "confidence": 0.64}]},
        source_report_id=1,
    )
    tool_facets.replace_analyzer_facets(
        s,
        "cite-checker",
        {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.8}],
         "technology": [{"value": "JavaScript", "confidence": 0.64}]},
        source_report_id=2,
    )


from backend import v1_facets


def test_tool_summary_shape():
    with db.session_scope() as s:
        _seed(s)
    payloads = v1_facets.tool_summaries(["sfedits"], matched_by_tool={"sfedits": [
        {"facet": "dependency", "value": "pypi:pywikibot", "confidence": 0.95}
    ]})
    assert payloads == [
        {
            "name": "sfedits",
            "title": "SF edits",
            "description": "stream",
            "url": "https://sfedits.example",
            "tool_type": "bot",
            "repository": "https://github.com/tieguy/sfedits",  # None when absent
            "deprecated": False,
            "keywords": ["edits"],
            "matched": [{"facet": "dependency", "value": "pypi:pywikibot", "confidence": 0.95}],
        }
    ]


def test_coverage_counts():
    with db.session_scope() as s:
        _seed(s)
    with db.session_scope() as s:
        assert v1_facets.coverage(s) == {"scannedTools": 2, "totalTools": 2}
```

**Step 2: Run to verify failure** — `ImportError: v1_facets`.

**Step 3: Implement**

Create `proxy/backend/v1_facets.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Public read-only facet discovery endpoints.

Answers "which tools carry signal X" (dependencies, Wikimedia APIs,
technologies, tool types) from the ToolSignalFacet index. Every response
carries coverage metadata: analyzer facets exist only for tools whose source
repository has been scanned, so an empty result must never read as "no tool
does this."
"""

from typing import Any

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import canonical_tools, db, tool_facets
from backend.models import FACET_TYPES, CanonicalToolCache

v1_facets_bp = Blueprint("v1_facets", __name__)

# Query parameter name -> facet_type. Kept explicit so URL surface and DB
# vocabulary can evolve independently.
# Query parameter -> ToolSignalFacet.facet_type (analyzer-detected signals).
FILTER_PARAMS = {
    "dependency": "dependency",
    "api": "wikimedia_api",
    "technology": "detected_technology",
}
# Query parameter -> CatalogFacetValue.field (declared catalog metadata).
# Separate map because these live in a different table with different
# coverage: every tool has declared metadata, only scanned tools have
# detected signals.
DECLARED_FILTER_PARAMS = {
    "tool_type": "tool_type",
    "keyword": "keywords",
    "wiki": "wiki",
    "license": "license",
}
DEFAULT_LIMIT = 25
# Hard-capped by the canonical serializer: tools_by_name truncates its input
# to MAX_QUERY_NAMES (canonical_tools.py:23,294), so asking for more would
# return husk records with empty titles for everything past the cap.
MAX_LIMIT = canonical_tools.MAX_QUERY_NAMES


def coverage(s: Session) -> dict[str, int]:
    """Scanned-vs-total tool counts every facet answer must disclose."""
    total = int(s.execute(select(func.count(CanonicalToolCache.tool_name))).scalar() or 0)
    return {"scannedTools": tool_facets.scanned_tool_count(s), "totalTools": total}


def tool_summaries(
    names: list[str], *, matched_by_tool: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Shared discovery tool shape, derived from cached canonical records.

    One shape across search, facets, and (later) the MCP tools, so clients
    never branch on which retrieval route produced a tool.
    """
    records = canonical_tools.tools_by_name(names)
    summaries = []
    for name in names:
        payload = records.get(name)
        record = payload.get("record") if payload else None
        source = record if isinstance(record, dict) else {}
        keywords = source.get("keywords")
        summaries.append(
            {
                "name": name,
                "title": str(source.get("title") or ""),
                "description": str(source.get("description") or ""),
                "url": str(source.get("url") or ""),
                "tool_type": str(source.get("tool_type") or ""),
                # null (not "") when absent — the published tool-record
                # contract, which the future /v1/similar-tools/ also honors.
                "repository": str(source["repository"]) if source.get("repository") else None,
                "deprecated": bool(source.get("deprecated")),
                "keywords": [str(k) for k in keywords] if isinstance(keywords, list) else [],
                "matched": matched_by_tool.get(name, []),
            }
        )
    return summaries
```

**Step 4: Run tests** — PASS. Note the module-level `from backend import v1_facets` import placement in the test file: move it to the top with the other imports (written inline above only for narrative order).

**Step 5: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/v1_facets.py tests/proxy/test_v1_facets.py
git commit -m "feat: shared tool summary and coverage for facet discovery"
```

---

### Task 2: `/v1/facets/tools/` and `/v1/facets/values/` routes

**Files:**
- Modify: `proxy/backend/v1_facets.py` (add routes)
- Modify: `proxy/backend/__init__.py:91-110` (register blueprint alongside its peers)
- Test: `tests/proxy/test_v1_facets.py` (extend)

**Step 1: Write the failing contract tests**

```python
def test_facets_tools_intersection_and_shape(client):
    with db.session_scope() as s:
        _seed(s)
    resp = client.get("/v1/facets/tools/?dependency=pywikibot&api=wikidata-query-service")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data) == {"tools", "total", "appliedFilters", "coverage"}
    assert [t["name"] for t in data["tools"]] == ["sfedits"]
    # Keyed by the query-parameter names the caller sent, so a response can
    # be round-tripped straight back into a new request.
    assert data["appliedFilters"] == {
        "dependency": ["pypi:pywikibot"],
        "api": ["wikidata-query-service"],
    }
    assert data["coverage"] == {"scannedTools": 2, "totalTools": 2}


def test_facets_tools_dependency_shorthand(client):
    """A bare package name matches any ecosystem; an explicit prefix pins one."""
    with db.session_scope() as s:
        _seed(s)
    bare = client.get("/v1/facets/tools/?dependency=pywikibot").get_json()
    pinned = client.get("/v1/facets/tools/?dependency=pypi:pywikibot").get_json()
    assert {t["name"] for t in bare["tools"]} == {"cite-checker", "sfedits"}
    assert {t["name"] for t in pinned["tools"]} == {"cite-checker", "sfedits"}


def test_facets_tools_rejects_no_filters_and_bad_limit(client):
    assert client.get("/v1/facets/tools/").status_code == 400
    resp = client.get("/v1/facets/tools/?dependency=x&limit=9999")
    assert resp.status_code == 200
    assert resp.get_json()["tools"] == []  # clamped, empty, still carries coverage


def test_facets_tools_unknown_values_match_nothing(client):
    """Seeded, so these assertions can fail for the right reason."""
    with db.session_scope() as s:
        _seed(s)
    solo = client.get("/v1/facets/tools/?dependency=nosuchpkg").get_json()
    assert solo["tools"] == [] and solo["total"] == 0
    # An unknown value combined with a valid filter must EMPTY the result,
    # never silently widen the AND to just the valid filter.
    mixed = client.get(
        "/v1/facets/tools/?dependency=nosuchpkg&api=wikidata-query-service"
    ).get_json()
    assert mixed["tools"] == [] and mixed["total"] == 0


def test_facets_tools_limit_never_exceeds_serializer_cap(client):
    """Every returned tool must carry real record data, even at the cap."""
    from backend import canonical_tools as ct

    with db.session_scope() as s:
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
            tool_facets.replace_analyzer_facets(
                s, name, {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.9}]},
                source_report_id=i,
            )
    data = client.get(f"/v1/facets/tools/?dependency=pywikibot&limit=9999").get_json()
    assert len(data["tools"]) <= ct.MAX_QUERY_NAMES
    assert all(t["title"] for t in data["tools"])  # no husk records


def test_facets_values_listing_and_validation(client):
    with db.session_scope() as s:
        _seed(s)
    resp = client.get("/v1/facets/values/?type=dependency")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data) == {"type", "values", "totalValues", "coverage"}
    assert data["values"][0] == {"value": "pypi:pywikibot", "toolCount": 2}
    assert data["totalValues"] == len(data["values"])
    limited = client.get("/v1/facets/values/?type=technology&limit=1").get_json()
    # _seed gives sfedits "python" and cite-checker "javascript", so
    # len(values) == 1 while totalValues == 2 discloses the truncation.
    assert len(limited["values"]) == 1
    assert limited["totalValues"] == 2
    assert client.get("/v1/facets/values/?type=bogus").status_code == 400
    assert client.get("/v1/facets/values/").status_code == 400
    assert client.get("/v1/facets/tools/?dependency=").status_code == 400  # empty value ≠ filter
```

**Step 2: Run to verify failure** — 404s (routes absent).

**Step 3: Implement the routes**

Append to `proxy/backend/v1_facets.py`:

```python
def dependency_values(s: Session, raw: list[str]) -> list[str]:
    """Expand bare package names to every ecosystem-prefixed stored value.

    Stored dependency values are "{ecosystem}:{name}" (source_analyzer.py);
    requiring callers to know the ecosystem would make the obvious query
    ("pywikibot") silently return nothing.
    """
    expanded: list[str] = []
    for value in raw:
        clean = str(value or "").strip().casefold()
        if not clean:
            continue
        if ":" in clean:
            expanded.append(clean)
            continue
        expanded.extend(
            s.execute(
                select(tool_facets.ToolSignalFacet.value)
                .where(
                    tool_facets.ToolSignalFacet.facet_type == "dependency",
                    tool_facets.ToolSignalFacet.value.like(f"%:{clean}"),
                )
                .distinct()
            ).scalars()
        )
    return expanded


@v1_facets_bp.route("/v1/facets/tools/")
def v1_facets_tools() -> Response | tuple[Response, int]:
    """Tools matching every supplied facet filter (AND across types)."""
    limit = request.args.get("limit", "")
    try:
        capped = max(1, min(MAX_LIMIT, int(limit))) if limit else DEFAULT_LIMIT
    except ValueError:
        capped = DEFAULT_LIMIT
    with db.session_scope() as s:
        filters: dict[str, list[str]] = {}
        declared: dict[str, list[str]] = {}
        applied: dict[str, list[str]] = {}
        # Declared filters first; same emptiness rule, different table.
        for param, field in DECLARED_FILTER_PARAMS.items():
            raw_values = [v for raw in request.args.getlist(param) for v in raw.split(",")]
            requested = sorted({str(v).strip().casefold() for v in raw_values if str(v).strip()})
            if not requested:
                continue
            declared[field] = requested
            applied[param] = requested
        for param, facet_type in FILTER_PARAMS.items():
            raw_values = [v for raw in request.args.getlist(param) for v in raw.split(",")]
            requested = sorted({str(v).strip().casefold() for v in raw_values if str(v).strip()})
            if not requested:
                # `?dependency=` (no value at all) is not a filter and must
                # not bypass the at-least-one-filter check below.
                continue
            values = dependency_values(s, requested) if facet_type == "dependency" else requested
            cleaned = sorted({str(v).strip().casefold() for v in values if str(v).strip()})
            # An UNKNOWN value is still a filter: it legitimately matches
            # nothing (200 + empty tools), it does not invalidate the request.
            # Emptiness is decided on the raw request value above, never on
            # the expansion result — tools_matching_facets/count_matching
            # treat an asked-for-but-empty value list as matching nothing
            # (they must never drop it, which would widen the AND).
            filters[facet_type] = cleaned
            # Echo under the caller's parameter name so responses round-trip
            # into new requests without knowing internal facet-type names.
            applied[param] = cleaned or requested
        if not filters and not declared:
            return jsonify({"error": "at least one facet filter is required"}), 400
        matches = tool_facets.tools_matching_facets(
            s, filters, declared_filters=declared, limit=capped
        )
        # True total, not page size: 50-of-50 and 50-of-800 must differ.
        total = tool_facets.count_matching(s, filters, declared_filters=declared)
        disclosed_coverage = coverage(s)
    matched_by_tool = {m.tool_name: m.matched for m in matches}
    return jsonify(
        {
            "tools": tool_summaries([m.tool_name for m in matches], matched_by_tool=matched_by_tool),
            "total": total,
            "appliedFilters": applied,
            "coverage": disclosed_coverage,
        }
    )


@v1_facets_bp.route("/v1/facets/values/")
def v1_facets_values() -> Response | tuple[Response, int]:
    """Top distinct values for one facet type, ranked by tool adoption."""
    facet_type = str(request.args.get("type") or "").strip().casefold()
    if facet_type not in FACET_TYPES:
        return jsonify({"error": f"type must be one of {sorted(FACET_TYPES)}"}), 400
    raw_limit = request.args.get("limit", "")
    try:
        limit = int(raw_limit) if raw_limit else tool_facets.DEFAULT_VALUE_RESULTS
    except ValueError:
        limit = tool_facets.DEFAULT_VALUE_RESULTS
    listing = cached_facet_values(facet_type, limit=limit)  # from Task 3
    with db.session_scope() as s:
        disclosed_coverage = coverage(s)
    return jsonify(
        {
            "type": facet_type,
            "values": listing["values"],
            "totalValues": listing["totalValues"],
            "coverage": disclosed_coverage,
        }
    )
```

(Before Task 3 lands the caching, implement `cached_facet_values` as a thin uncached wrapper with the same signature so this route's contract doesn't change when caching arrives.)

In `dependency_values`, import `ToolSignalFacet` from `backend.models` directly (add it to the module's import block) rather than reaching through `tool_facets`. The name is deliberately public: Phase 4's MCP `facet_tools` handler calls it too.

Register the blueprint in `proxy/backend/__init__.py`: add the import and `app.register_blueprint(v1_facets_bp)` next to the existing `v1_statistics` registration (match its exact style, lines 91-110).

**Step 4: Run tests** — PASS; then the full suite + coverage:

Run: `PYTHONPATH=proxy pytest tests/proxy -q --cov --cov-report=term-missing`
Expected: PASS, ≥ 91.7%. Add tests for any uncovered branch (empty-limit parse path, dependency expansion with explicit prefix, unknown filter param ignored).

**Step 5: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/v1_facets.py proxy/backend/__init__.py tests/proxy/test_v1_facets.py
git commit -m "feat: add facet discovery endpoints"
```

---

### Task 3: Rate limiting and value-count caching

Design Phase 4 requires rate limiting on `/v1/facets/*` (shipped here, where the routes are born, not deferred), and the design's Existing Patterns section requires `facets/values/` counts to reuse the `catalog_statistics` snapshot idiom (`SNAPSHOT_MAX_AGE`, 15 minutes) — these are unauthenticated aggregate queries the MCP server will fan out to.

**Files:**
- Modify: `proxy/backend/__init__.py` (`register()`, line 67 — ProxyFix, guarded by env var)
- Modify: `proxy/backend/security.py` (facet read limiter)
- Modify: `proxy/backend/v1_facets.py` (limiter checks; cached value counts)
- Modify: `docs/deploy-toolforge.md` (measure + set the new env var on Toolforge)
- Test: `tests/proxy/test_v1_facets.py` (extend)

**Step 1: Client identity must precede per-IP limiting.** `proxy/backend/v1.py:432-451` documents that `request.remote_addr` behind Toolforge's ingress is the proxy's address and no `ProxyFix` is installed — a per-IP limiter keyed on it would be one global bucket (60 req/min for the whole world, then 429s for everyone). Two constraints shape the fix:

- It goes in `backend.register()` (`proxy/backend/__init__.py:67`), NOT `proxy/app.py`: CI holds `proxy/app.py` to 100% branch coverage (`.github/workflows/ci.yml:95`), and a module-level env-guarded branch there is untestable without `importlib.reload`. `register()` is exercised by every endpoint test, and `v1.py:433`'s own docstring says the hop count belongs in `backend.register`.
- The hop count is **measured, not assumed**: `v1.py:439-447` exists precisely because N cannot be guessed safely — too high and clients spoof `X-Forwarded-For` to mint unlimited rate-limit buckets.

```python
# In backend.register(), before blueprint registration:
proxy_hops = int(os.environ.get("TOOLHUB_PROXYFIX_X_FOR", "0") or 0)
if proxy_hops:
    from werkzeug.middleware.proxy_fix import ProxyFix

    # N is measured per deployment via /v1/debug/forwarded/ (see
    # docs/deploy-toolforge.md); trusting more hops than the ingress
    # actually appends lets clients forge their address.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops)
```

In `docs/deploy-toolforge.md`, document the procedure: open `https://toolhub-evolved.toolforge.org/v1/debug/forwarded/` **from a signed-in browser session** on a machine whose public IP you know (the route is `@login_required`, `v1.py:429-430` — an unauthenticated curl gets a redirect and a misleading result), read which `candidates` row matches that IP (the route's docstring at `v1.py:429-451` explains the arithmetic), set `TOOLHUB_PROXYFIX_X_FOR` to that N, and then delete the temporary debug route as its docstring instructs. Test: build the app with the env var set (monkeypatch `os.environ` before calling `backend.register`), send a request with `X-Forwarded-For: 203.0.113.7` to any registered route, and assert the effective `request.remote_addr` is `203.0.113.7` (a probe route registered in the test works); also test that with the var unset the middleware is not installed.

**Step 2: Facet read limiter.** In `security.py`, add `FACET_READ_LIMIT_PER_WINDOW` (120 per rolling window, matching the existing window constant), a limiter instance, `facet_rate_limited(client_addr)` mirroring `read_rate_limited` (line 130), and registration in `clear_rate_limits()`. At the top of both `v1_facets` routes:

```python
    if security.facet_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
```

Test: monkeypatch `facet_rate_limited` to `True`, assert 429 from both routes (the fixture already calls `security.clear_rate_limits()`).

**Note on `/v1/facets/values/?type=`:** the accepted vocabulary is the union of the detected types (`FACET_TYPES`) and the declared fields (`DECLARED_FILTER_PARAMS` values); dispatch to `tool_facets.facet_value_counts` or an equivalent `CatalogFacetValue` counter accordingly, and label each response with which family it came from (add `"family": "detected" | "declared"`) so a caller can tell whether the coverage caveat applies to it. The 400-on-unknown-type behavior and the bounded-plus-`totalValues` contract are unchanged.

**Step 3: Cached value counts.** Add a cached accessor to `v1_facets.py` that both the REST route and Phase 4's MCP tool call:

```python
def cached_facet_values(facet_type: str, *, limit: int) -> dict[str, Any]:
    """Value counts + truncation info, cached per worker for 15 minutes."""
```

The function's FIRST action clamps `limit` to `[1, tool_facets.MAX_VALUE_RESULTS]` — before the cache lookup — so hostile `?limit=` values cannot mint one cache entry per distinct integer on a public route. Deliberate simplification, stated for reviewers: this is a **per-worker module dict** (keyed by `(facet_type, clamped_limit)` — a bounded keyspace of 4 types × 500 limits, timestamped, `VALUES_MAX_AGE = timedelta(minutes=15)`, plus a `clear_cache()` helper for tests) — NOT `catalog_statistics.py`'s cross-worker `ApiCacheMeta`-row-plus-advisory-lock machinery. The underlying query is one bounded GROUP BY over an indexed table; N workers each refreshing it every 15 minutes is fine, and the DB-row idiom's complexity buys nothing here. The returned dict carries `values` (from `tool_facets.facet_value_counts(s, facet_type, limit=limit)`) and `totalValues` (from `tool_facets.count_facet_values`), so responses disclose truncation. Tests call `clear_cache()` in the fixture (alongside `clear_rate_limits()`) and cover the cached path (second call returns the same object without a query — monkeypatch `facet_value_counts` to count invocations) and the expiry path (monkeypatch the module's clock source).

**Step 4: Run the touched tests, then the full suite + coverage. Lint and commit:**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/__init__.py proxy/backend/security.py proxy/backend/v1_facets.py docs/deploy-toolforge.md tests/proxy/test_v1_facets.py
git commit -m "feat: rate-limit and cache facet discovery reads"
```

---

## Phase completion check

- Contract tests green for both endpoints: combined filters, dependency shorthand expansion, 400 on missing/unknown params, coverage on every response including empty results, no husk records at the limit cap.
- Rate limiting green: 429 path tested on both routes; ProxyFix restores real client addresses when `TOOLHUB_PROXYFIX_X_FOR=1`.
- Value-count caching green: repeated `/v1/facets/values/` calls within 15 minutes hit the snapshot, expiry refreshes it.
- Full suite + coverage ratchet green; ruff clean.
- Manual: with a populated dev DB, `curl 'localhost:8000/v1/facets/values/?type=dependency'` lists ecosystem-prefixed values with counts; `curl 'localhost:8000/v1/facets/tools/?dependency=pywikibot'` returns tool summaries with `matched` and `coverage`.
