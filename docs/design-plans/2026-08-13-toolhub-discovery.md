# Toolhub Discovery (Prior-Art Search) Design

## Summary

This design adds a prior-art search capability to toolhub-evolved, the catalog
of roughly 4,500 Wikimedia community tools, so that someone starting a new
Wikimedia-related project can quickly discover whether something similar
already exists — and, if so, what libraries and Wikimedia APIs it uses. The
work has two deliverables joined by a shared contract. Server-side,
toolhub-evolved gains a new facet index (structured signals like dependencies
and detected Wikimedia APIs, extracted from the source-code scans it already
runs) and upgrades its existing text search from date-ordered matching to
relevance-ranked search. Both capabilities are exposed twice — as REST
endpoints and as an MCP server — so any MCP-capable client (Claude Code,
claude.ai, and others) can query the catalog directly. Client-side, a thin
Claude skill (`toolhub-discovery`) packages the search methodology — how to
phrase queries, when to caveat missing coverage, how to structure a
build/reuse/differentiate report — without embedding any HTTP or
Wikimedia-fetching code of its own; all upstream traffic stays server-side
under toolhub-evolved's existing identity.

The approach favors an explicit two-track split: one kind of query answers
"is there already a tool like this" (full-catalog text search over titles,
descriptions, and keywords), and another answers "what do tools with similar
technical needs actually use" (facet lookups over the ~36% of tools with
scanned repositories). Because facet coverage is partial, every facet
response carries coverage metadata so absence of a match is never misread as
absence of the underlying tool. The design deliberately avoids server-side
similarity scoring — the LLM client judges similarity from retrieved
candidates — leaving an embeddings-based `/v1/similar-tools/` endpoint as a
documented future addition that plugs into the same tool-record contract
rather than requiring rework.

## Definition of Done

- From any MCP-capable client (Claude Code, claude.ai, others), adding the
  toolhub-evolved MCP server is sufficient to run a **prior-art review** of a
  greenfield Wikimedia tool idea: the review reports (a) existing tools that do
  or nearly do the same thing, drawn from the full ~4,500-tool catalog, and
  (b) the libraries and data-access patterns actually used by tools with
  similar access needs, drawn from the scanned subset.
- Queries like "which tools depend on pywikibot" and "which tools use the
  Wikidata Query Service" are answerable via both REST and MCP, in one call.
- Tool search returns relevance-ranked results (BM25 or equivalent) instead of
  `LIKE` matches ordered by fetch date.
- Every pattern-side answer carries its coverage caveat (facets exist only for
  tools with scanned repositories, ~36% of the catalog) so "no match found" is
  never presented as "no tool does this."
- A shareable `toolhub-discovery` Claude skill exists that encodes the review
  methodology and delegates all retrieval to the MCP server. It contains no
  HTTP code of its own.
- Validation: a search for a known duplicate cluster (link-analysis tools
  `linkdata` / `linkrecnext` / `findlinkfast`) retrieves all three; precision
  spot-checks against the operator's existing projects (sfedits,
  alex-cite-checker) produce relevant top hits.

## Glossary

- **Toolhub / toolhub-evolved**: Toolhub (toolhub.wikimedia.org) is
  Wikimedia's official catalog of roughly 4,500 community tools (bots,
  gadgets, apps). toolhub-evolved — the codebase this design extends — is a
  companion service that reads Toolhub as its source of truth and layers
  enrichment (source-code scans, identity data) on top.
- **MCP (Model Context Protocol)**: An open protocol that lets LLM clients
  (Claude Code, claude.ai, and others) call external tools and prompts over a
  standard interface. This design adds an MCP server so any compliant client
  can query the catalog directly, without bespoke integration code.
- **Prior-art review**: The workflow this design enables — searching existing
  tools and their technical patterns before starting a new project, to avoid
  duplicating work and to see what approaches similar tools already use.
- **Facet / facet index**: A structured, filterable attribute extracted from
  a tool's source code or metadata (e.g., "depends on pywikibot", "uses the
  Wikidata Query Service"). The facet index is the new database table that
  makes these attributes queryable instead of buried in unstructured JSON.
- **BM25**: A standard text-relevance ranking algorithm (used by search
  engines and full-text search extensions) that scores how well a document
  matches a query; it replaces the current fetch-date ordering.
- **Toolforge**: The Wikimedia Foundation's hosting platform for
  community-run tools and bots. toolhub-evolved is deployed there, and this
  design updates its Toolforge deployment configuration.
- **pywikibot**: A widely-used Python library for scripting interactions
  with Wikimedia wikis; used in this document as an example dependency a
  facet query might search for.
- **Wikidata Query Service (WDQS)**: A SPARQL-based query endpoint for
  Wikidata; used in this document as an example of a Wikimedia API a tool
  might be detected as using.
- **SQLite FTS5 / MariaDB FULLTEXT**: The full-text search features built
  into each database engine toolhub-evolved runs on (SQLite in development,
  MariaDB in production). The ranked-search design uses whichever is native
  to the active backend.
- **Streamable HTTP**: The MCP transport variant used here — plain HTTP
  request/response rather than a persistent Server-Sent-Events connection —
  chosen because the server's answers don't need to stream incrementally.
- **ASGI / WSGI**: Two standard interfaces Python web servers use to talk to
  frameworks. The design must decide whether to mount the MCP SDK (which
  expects ASGI) alongside the existing Flask app (which is WSGI-based).
- **`CanonicalToolCache`**: The existing database model holding each tool's
  official, curated record (name, description, URL, etc.) — the source of
  full-catalog search.
- **`SourceAnalysisReport`**: The existing database model holding the raw
  output of automated repository scans (detected dependencies, APIs,
  technologies) for the subset of tools with a linked source repository —
  the source the new facet index is built from.
- **Claude skill**: A packaged, shareable instruction set (here,
  `toolhub-discovery`) that teaches a Claude-based client a specific
  workflow without containing its own retrieval code — it directs the
  client to call the MCP server instead.
- **Coverage (facet coverage)**: Metadata attached to facet responses
  stating what fraction of the catalog was actually scanned, so a "no
  match" result is never misread as proof that no tool does something.

## Architecture

Two deliverables with a clean seam: **toolhub-evolved grows a retrieval layer**
(facet index, ranked search, REST endpoints, MCP server), and a **thin Claude
skill supplies methodology only**. No similarity scoring lives server-side in
this design; the LLM client judges similarity from retrieved candidates. A
future embeddings-based `/v1/similar-tools/` endpoint slots in as one more
retrieval route behind the same response contract.

Data flow:

```
project idea (user)
  └─ skill / MCP `prior-art-review` prompt
       ├─ search_tools(query…)        ← ranked text search, full catalog
       ├─ list_facet_values(type)     ← what the ecosystem actually uses
       ├─ facet_tools(dependency=…, api=…)  ← scanned subset (~36%)
       └─ LLM reads candidates → prior-art report
            (build/reuse/differentiate · adjacent tools · recommended stack)
```

Server-side, everything derives from data already collected:

- `CanonicalToolCache` (`proxy/backend/models.py`) — official records; source
  of `search_text` and canonical facets (`tool_type`).
- `SourceAnalysisReport` — per-repo analyzer output (dependencies, detected
  Wikimedia APIs, technologies) currently stored as unqueryable JSON; the new
  facet index makes it queryable.
- The hourly `proxy/repository_scan.py` job keeps reports fresh; a hook keeps
  facets in sync.

### Retrieval contracts

All retrieval routes (REST and MCP) return one tool-record shape:

```json
{
  "name": "…", "title": "…", "description": "…", "url": "…",
  "tool_type": "…", "repository": null, "deprecated": false,
  "keywords": ["…"],
  "matched": [{"facet": "dependency", "value": "pypi:pywikibot", "confidence": 0.9}]
}
```

REST endpoints (read-only, unauthenticated):

```
GET /v1/facets/tools/?dependency=pywikibot&api=wdqs&technology=python&tool_type=bot&limit=50
  → { "tools": [ToolRecord…], "total": n,
      "appliedFilters": {…},
      "coverage": {"scannedTools": n, "totalTools": 4474} }

GET /v1/facets/values/?type=dependency
  → { "values": [{"value": "pypi:pywikibot", "toolCount": 87}, …],
      "coverage": {…} }

GET /v1/search/tools/?q=…          (existing shape; gains relevance ordering)
```

MCP server (streamable HTTP at `/mcp`, read-only, no auth):

- Tools: `search_tools(query, limit)`, `facet_tools(dependency?, api?,
  technology?, tool_type?, limit)`, `list_facet_values(type)`,
  `get_tool(name)` — thin wrappers over the same handlers as REST.
- Prompt: `prior-art-review(project_description)` — ships the workflow
  (characterize idea → dual retrieval → judged report) so the methodology
  travels with the server to every MCP client.

Because all upstream Wikimedia traffic happens server-side under
toolhub-evolved's existing User-Agent, skill users run no Wikimedia-bound code
and there is no per-deployment identity to configure client-side.

### Facet index

New table `ToolSignalFacet` in `proxy/backend/models.py`:

```python
tool_name: str            # matches CanonicalToolCache.tool_name
facet_type: str           # 'dependency' | 'wikimedia_api' | 'technology' | 'tool_type'
value: str                # normalized: 'pypi:pywikibot', 'wdqs', 'python', 'bot'
confidence: float         # from analyzer; 1.0 for canonical-record facets
source_report_id: int | None
updated_at: datetime
# unique (tool_name, facet_type, value); index (facet_type, value)
```

Populated two ways: an idempotent backfill over stored `SourceAnalysisReport`
rows plus canonical `tool_type` values, and an incremental hook when
`repository_scan.py` stores a new report. Dependency values are namespaced by
ecosystem (`pypi:`, `npm:`, …); `wikimedia_api` values reuse the analyzer's
detector names.

### Ranked search

`canonical_tools.search()` keeps its signature but gains relevance ranking,
with dialect-specific backends behind one interface: SQLite FTS5 (`bm25()`)
in development, MariaDB InnoDB FULLTEXT (natural-language relevance) on
Toolforge. `search_text` derivation additionally folds in canonical
`keywords`, which it currently omits. `/v1/search/tools/` response shape is
unchanged; only ordering improves.

## Existing Patterns

Investigation (2026-08-13) found and this design follows:

- **Feature-module endpoints:** `/v1/` routes live in per-feature modules
  (`proxy/backend/v1_statistics.py`, `v1_source_analysis.py`). Facet endpoints
  follow as `proxy/backend/v1_facets.py`; the MCP server as
  `proxy/backend/mcp_server.py`.
- **Schema in one place:** all tables in `proxy/backend/models.py`
  (SQLAlchemy, SQLite dev / MariaDB prod).
- **Derived-data jobs:** scheduled Toolforge jobs in `jobs.yaml`
  (e.g., hourly `repository_scan`). Facet backfill runs as a one-shot job;
  incremental updates ride the existing scan job.
- **Snapshot caching:** `catalog_statistics.py` caches expensive aggregates
  (15 min). `facets/values/` counts reuse this pattern.

Divergence: an MCP endpoint has no precedent in the repo. It is additive —
REST endpoints remain the primary contract; MCP wraps the same handlers.

## Implementation Phases

### Phase 1: Facet index

**Goal:** Analyzer output becomes queryable.

**Components:**
- `ToolSignalFacet` model in `proxy/backend/models.py`
- Extraction/normalization from `SourceAnalysisReport` JSON + canonical
  `tool_type`, in a new `proxy/backend/tool_facets.py`
- Idempotent backfill entry point (Toolforge one-shot job in `jobs.yaml`)
- Incremental hook in `proxy/repository_scan.py` report-store path

**Dependencies:** none.

**Done when:** backfill on a copy of production data populates facets for all
stored reports; re-running changes nothing; unit tests cover extraction,
normalization (ecosystem prefixes, API detector names), and idempotency.

### Phase 2: Ranked search

**Goal:** Relevance-ordered tool search on both database backends.

**Components:**
- Dialect-aware ranking inside `proxy/backend/canonical_tools.py` (FTS5 index
  for SQLite; FULLTEXT index for MariaDB), same `search()` interface
- `search_text` derivation extended with canonical `keywords`

**Dependencies:** none (parallel with Phase 1).

**Done when:** `/v1/search/tools/` returns relevance-ordered results on both
backends; ranking smoke tests pass (fixed query → expected tool in top 5);
existing consumers unaffected (contract tests on response shape).

### Phase 3: Facet REST endpoints

**Goal:** "Which tools use X" answerable over HTTP.

**Components:**
- `proxy/backend/v1_facets.py` — `/v1/facets/tools/` and `/v1/facets/values/`
  per the contracts above, including `coverage` metadata
- Shared tool-record serializer used by search and facet responses

**Dependencies:** Phase 1.

**Done when:** contract tests pass for both endpoints, including combined
filters, empty results carrying `coverage`, and input validation.

### Phase 4: MCP server

**Goal:** Any MCP client can query the catalog and receive the workflow.

**Components:**
- `proxy/backend/mcp_server.py` — streamable-HTTP endpoint at `/mcp` exposing
  the four tools and the `prior-art-review` prompt, wrapping Phase 2/3 handlers
- Rate limiting on `/mcp` and `/v1/facets/*` (per-IP, modest defaults)
- Integration decision recorded at implementation time: official Python MCP
  SDK via ASGI sub-mount vs. native Flask JSON-RPC handling (stateless
  streamable HTTP; plain JSON responses suffice — no SSE required). Prefer the
  SDK unless mounting it under the existing WSGI app proves disproportionate.
- Toolforge deployment update (`docs/deploy-toolforge.md`, webservice config)

**Dependencies:** Phases 2 and 3.

**Done when:** an MCP SDK test client lists tools/prompts and exercises each
end-to-end against a local server; deployed endpoint answers the same from
`toolhub-evolved.toolforge.org/mcp`; rate limit returns 429 under burst.

### Phase 5: toolhub-discovery skill + validation

**Goal:** Shareable methodology layer, validated against real projects.

**Components:**
- `skills/toolhub-discovery/SKILL.md` in this repo (installable by copy):
  when to invoke (greenfield ideation), idea characterization (multiple
  phrasings; predicted data access; one clarifying question if too thin),
  dual retrieval via MCP tools, report format
  (build/reuse/differentiate · adjacent tools · recommended stack, every claim
  citing a tool name), mandatory caveats (facet coverage, deprecated tools
  flagged not hidden), and the no-fallback rule (MCP absent → instruct to add
  the server, never hand-roll fetches)
- Regression probes recorded alongside the skill: known duplicate cluster
  (`linkdata`/`linkrecnext`/`findlinkfast`) plus 1–2 more identified during
  validation

**Dependencies:** Phase 4.

**Done when:** cluster probe retrieves all three tools; prior-art runs against
the operator's existing projects produce relevant top hits (precision judged
by the operator) and at least one previously unknown related tool or library
surfaced counts as the surprise-yield success signal.

## Additional Considerations

**Coverage honesty.** Facets cover only tools with scanned repositories
(repository field populated: 1,617 of 4,474 tools, 36% as of 2026-08-13).
Every facet response carries `coverage` so clients cannot silently
overclaim. Description-based search covers the full catalog (title,
description, url are 100% populated).

**Deliberately out of scope (decided 2026-08-13):** analyzing on-wiki user
scripts/gadgets (~1,000 tools; upstream Toolhub work may address repository
metadata) and any server-side similarity scoring. The embeddings variant
(`/v1/similar-tools/` + `similar_tools` MCP tool) is a planned follow-on, not
part of this design; the shared tool-record contract is the seam it plugs
into.

**Abuse surface.** A public MCP endpoint invites automated LLM-agent traffic;
rate limiting ships in Phase 4, not later. All endpoints are read-only.

**Spec churn.** MCP streamable HTTP is young; pinning the SDK version and
keeping the endpoint stateless minimizes exposure.
