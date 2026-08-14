# Toolhub Discovery Implementation Plan — Phase 2: SUPERSEDED

> **This phase was built, then reverted. Do not implement it.** Kept as a record so the decision is not re-litigated.

**What it was:** relevance-ranked canonical search built locally — SQLite FTS5 virtual table + triggers, a MariaDB InnoDB FULLTEXT index, prefix-token matching, a LIKE top-up to protect substring recall, and two migrations. Implemented in commit `506568f`, reverted in `baf6877`.

**Why it was reverted (2026-08-13):** the MCP's `search_tools` exists to answer prior-art questions, and **upstream Toolhub already provides relevance-ranked search that is better at exactly those queries.** Verified against the live API:

| Query                                          | Upstream `/api/search/tools/`                 | Our planned local implementation            |
| ---------------------------------------------- | --------------------------------------------- | ------------------------------------------- |
| `citation`                                     | 58 hits, all genuinely citation tools, ranked | LIKE match set, ordered by cache-fetch date |
| `find unsourced statements needing references` | reference validators + Citation Needed tools  | implicit AND across tokens → ~nothing       |
| `citat` (partial word)                         | 58 hits                                       | needed bespoke prefix-token handling        |

The concept-query row is decisive: an LLM composing a prior-art search sends sentences, not keywords, and our token-AND design would have returned almost nothing for them.

**What replaces it:** Phase 4's `search_tools` calls `toolhub.public_api_get("/api/search/tools/", params={"q": ..., "page_size": ...})` — the repo's established anonymous upstream read path, which already carries the compliant User-Agent, the shared `ApiCache`, and timeout/error handling (used the same way by `proxy/catalog_sync.py:292`). `canonical_tools.search()` keeps its existing LIKE behavior as the degraded fallback for when upstream is unavailable, exactly as before this phase.

**What was deliberately given up:** relevance ranking for toolhub-evolved's own web UI search box (`public_html/views/search.js` still gets fetch-date ordering via `/v1/canonical/tools/?q=`), and independence from upstream availability at query time. Both were judged not worth a deploy-time MariaDB table rebuild plus permanent maintenance of FTS5 triggers and dialect-specific SQL. If the web UI's search quality becomes a priority later, this is a self-contained piece of work to revisit on its own merits — see `506568f` for a complete, tested implementation.

**Consequence for later phases:** Phase 3 no longer "benefits from Phase 2's keyword-rich records" — canonical `search_text` still omits `keywords`, which only affects the local fallback path. Phase 4 gains an upstream dependency for `search_tools` and must handle upstream failure explicitly.
