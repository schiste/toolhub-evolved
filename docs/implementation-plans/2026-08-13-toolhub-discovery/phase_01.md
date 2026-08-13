# Toolhub Discovery Implementation Plan — Phase 1: Analyzer Facets in the Catalog Projection

> **For Claude:** REQUIRED SUB-SKILL: Use ed3d-plan-and-execute:executing-an-implementation-plan to implement this plan task-by-task.

**Goal:** Make the analyzer signals already collected in `SourceAnalysisReport` (dependencies, Wikimedia APIs, detected technologies) queryable, by emitting them as facets into the existing `catalog_facet_values` table alongside the declared metadata facets already there.

**Architecture:** No new table. `catalog_projection._replace_facets` gains a second emission pass that derives facets from the tool's latest analysis report. Query helpers live in `proxy/backend/tool_facets.py` over `CatalogFacetValue`. Freshness and backfill come free from the existing pipeline.

**Tech Stack:** Python 3.11+/3.13, Flask 3, SQLAlchemy 2, pytest with in-memory SQLite.

**Scope:** Phase 1 of 5 from `docs/design-plans/2026-08-13-toolhub-discovery.md`.

**Codebase verified:** 2026-08-13. **Design revised 2026-08-13** (see below) after the original two-table design was disproven.

---

## Design history — read this before changing anything

The first draft of this phase created a separate `ToolSignalFacet` table. That was **wrong and has been reverted.** The stated justification was that `catalog_projection._latest_reports` (`catalog_projection.py:187-199`) only consumes reports with `review_status == REVIEW_APPROVED`, implying a human gate that would shrink discovery coverage. **That is false:** `proxy/repository_scan.py:289` writes `review_status=REVIEW_APPROVED, reviewed_at=utcnow()` — the hourly auto-scan approves its own reports, precisely because a human gate would not scale. The projection therefore already sees every scanned report.

With that corrected, the single-table design wins on every axis that matters:

| Concern | Separate table | Facets in the projection |
| --- | --- | --- |
| Freshness after a scan | new hook in `repository_scan.py` | free — `repository_scan.py:309` already calls `graph_enrichment.refresh_tool_names([tool_name])` → `catalog_projection.refresh_tool_names` (`graph_enrichment.py:242`) |
| Backfill | new batched migration | free — `migrate.py:77` already calls `catalog_projection.refresh_candidates` per deploy, plus the hourly 500-tool sweep (`jobs.yaml:110-116`) |
| Query shape | cross-table `INTERSECT`, two vocabularies | one table, one vocabulary |
| Rebuild invariant | second rebuild path to maintain | `catalog_facet_values` stays "everything rebuildable from this tool's projection inputs" — and analysis reports are ALREADY an input (`_report_patch`, `catalog_projection.py:180-184`) |

**Verified facts this phase relies on:**

- `CatalogFacetValue` (`proxy/backend/models.py:333-346`): `(tool_name, field, value)` unique; `value` casefolded on write, `label` original, `provenance` JSON, `confidence_basis_points` int 0-10000, `refreshed_at`.
- `_replace_facets` (`catalog_projection.py:353-378`) deletes ALL rows for the tool then re-inserts from `FACET_FIELDS` (`:79-88`: tool_type, keywords, wiki, technology, tasks, audiences, ui_language, license) against the **effective merged** record. It is called once per tool at `catalog_projection.py:452` inside `_refresh_batch`'s try block.
- `_latest_reports(s, names)` (`catalog_projection.py:187-199`) already returns the newest approved report per tool and is already called inside `_sources_by_tool` (`:244`). `_refresh_batch` will need it in its own scope — call it once per batch, do not call it per tool.
- Analyzer report shape (`source_analyzer.py:2801-2832`): top-level `"dependencies"`, `"apis"`, `"technology"` lists of finding payloads with keys `value`, `label`, `kind`, `category`, `confidence` (0.0-1.0), `evidence`. Dependency `value` is `"{ecosystem}:{name}"` (ecosystems: npm, pypi, composer, cargo, go, rubygems). API `value` is one of exactly: `mediawiki-action-api`, `wikibase-api`, `wikidata-query-service`, `mediawiki-rest-api`, `toolforge`, `commons-upload`.
- `SOURCE_REPOSITORY = "repository_analysis"` and `SOURCE_CONFIDENCE[SOURCE_REPOSITORY] = 75` already exist (`catalog_projection.py:41,93`).
- Tests: `PYTHONPATH=proxy pytest tests/proxy -q --cov`; ruff via CI's pin — `uvx ruff@0.14.9 check proxy` and `format --check proxy` (a newer local ruff reports unrelated pre-existing errors). Coverage ratchet is 91.7 and **already failing on main at 91.22** — do not make it worse; improving it is a bonus.

**Facet vocabulary added by this phase** (new `CatalogFacetValue.field` values, chosen not to collide with the declared eight):

| field | source | meaning |
| --- | --- | --- |
| `dependency` | report `dependencies` | `pypi:pywikibot` etc. |
| `wikimedia_api` | report `apis` | the six detector ids |
| `detected_technology` | report `technology` | language/framework detected in source — deliberately NOT `technology`, which is the DECLARED `technology_used` field |

**Confidence convention (must be documented in code):** for declared facets `confidence_basis_points` means *source authority* (`SOURCE_CONFIDENCE`). For these three analyzer fields it means *detection certainty*: `round(finding_confidence * 10000)`. Both are "how much to trust this row", which is why one column is acceptable, but the derivation differs and a reader must be told.

---

### Task 1: Emit analyzer facets from the projection

**Files:**
- Modify: `proxy/backend/catalog_projection.py`
- Test: `tests/proxy/test_catalog_projection.py` (exists — follow its fixtures)

**Step 1: Write the failing tests.** In the existing projection test module, add cases that project a tool whose latest `SourceAnalysisReport` carries dependencies/apis/technology, then assert `catalog_facet_values` rows:

- a `dependency` row with `value == "pypi:pywikibot"`, `label` preserving the analyzer's label, `confidence_basis_points == 9500` for a 0.95 finding;
- a `wikimedia_api` row for `wikidata-query-service`;
- a `detected_technology` row with `value == "python"` (casefolded) from a `"Python"` finding;
- `provenance` on each row identifying `repository_analysis` and the report id;
- declared facets for the same tool still present and unchanged (the two passes must not interfere);
- a tool with NO report projects declared facets only, and does not error;
- **reprojecting twice is idempotent** — same rows, no duplicates (the delete-then-rebuild already guarantees this; pin it);
- a malformed report (`report` not a dict, sections not lists, entries not dicts, missing/NaN confidence) projects declared facets and no analyzer rows, and does not raise.

**Step 2: Run to verify failure.**

**Step 3: Implement.** Add a pure extraction function beside `_replace_facets`:

```python
# Report section -> CatalogFacetValue.field for signals detected in source.
# Named apart from the declared FACET_FIELDS vocabulary: "detected_technology"
# is what the analyzer found in the code, "technology" is what the toolinfo
# record claims. They are different assertions and must stay distinguishable.
ANALYZER_FACET_FIELDS = (
    ("dependencies", "dependency"),
    ("apis", "wikimedia_api"),
    ("technology", "detected_technology"),
)


def _analyzer_facets(report: dict | None) -> list[tuple[str, str, str, int]]:
    """Return (field, value, label, confidence_basis_points) per detected signal.

    Pure so it can be exercised without a database. Duplicate values keep the
    highest confidence: the analyzer emits one finding per evidence source.
    """
```

Rules it must implement: skip non-dict reports and non-list sections; skip entries whose `value` is empty after strip; `value` casefolded and truncated to 255 (matching the declared path at `catalog_projection.py:357`); `label` from the finding's `label` else its `value`, truncated to 255; confidence coerced with `try/except (TypeError, ValueError)` to 0.0, clamped to 0.0-1.0, then `round(x * 10000)`; dedupe on `(field, value)` keeping max confidence.

Then extend `_replace_facets` to take the tool's latest report and emit those rows after the declared ones, with `provenance=[{"source": SOURCE_REPOSITORY, "reportId": <id>, "observed": <iso>}]`. Thread the reports through `_refresh_batch`: call `_latest_reports(s, names)` **once per batch** before the per-tool loop and index into it at the `_replace_facets` call site (`catalog_projection.py:452`).

Containment requirement: wrap the analyzer emission in its own `try/except (TypeError, ValueError)` that logs and continues, so a malformed report can never cost a tool its declared facets. (`_refresh_batch`'s outer handler at `:453` marks the whole batch failed — analyzer data must not be able to trigger that.)

**Step 4: Run tests; then the full suite + ruff.**

**Step 5: Commit.**

---

### Task 2: Query helpers over `CatalogFacetValue`

**Files:**
- Rewrite: `proxy/backend/tool_facets.py` (exists from the reverted design — retarget it, do not start over)
- Modify: `tests/proxy/test_tool_facets.py` (exists — the semantics tests below are already written and mutation-verified; keep them)

The existing module already implements the semantics this phase needs, against the wrong table. Retarget it to `CatalogFacetValue` and collapse the two filter families into one, since there is now only one table:

```python
def tools_matching_facets(
    s: Session, filters: dict[str, list[str]], *, limit: int = MAX_FACET_RESULTS
) -> list[FacetMatch]: ...
def count_matching(s: Session, filters: dict[str, list[str]]) -> int: ...
def facet_value_counts(
    s: Session, field: str, *, limit: int = DEFAULT_VALUE_RESULTS
) -> list[dict[str, Any]]: ...
def count_facet_values(s: Session, field: str) -> int: ...
def scanned_tool_count(s: Session) -> int: ...
```

**Behaviour that must survive the retarget unchanged** (each is already pinned by a test; two are mutation-verified):
- filters AND across fields, OR within a field;
- **fail closed**: an asked-for filter whose cleaned value list is empty returns `[]`/`0` immediately, never dropped (dropping silently widens the AND);
- `count_matching` counts DISTINCT tool names;
- ranking is by max confidence **among the facets that matched**, then tool name — not the tool's best unrelated facet;
- `FacetMatch.matched` contains **only** matched facets;
- `facet_value_counts` bounded, `count_facet_values` reports the true total.

Changes required by the retarget:
- `ToolSignalFacet.facet_type` → `CatalogFacetValue.field`; `confidence` (float 0-1) → `confidence_basis_points` (int 0-10000). `FacetMatch.matched` entries keep the float shape (`confidence_basis_points / 10000`) so the API contract in phases 3-4 is unchanged.
- `filters` keys are now the union vocabulary: the three analyzer fields plus the declared eight. Validate against that union; an unknown field behaves identically in all helpers (see the existing consistency test).
- `declared_filters=` is DELETED — one table, one dict. Update the Task 3b tests to the single-dict form; keep their coverage-independence assertion (a tool with no analysis report is still findable by a declared filter).
- `scanned_tool_count` still counts distinct `SourceAnalysisReport.tool_name` — coverage means "has a scanned repo", which is not answerable from the facet table now that both families live there.

**Verification:** after the retarget, re-run the mutation checks — remove the matched-condition from the ranking query and from the detail query in turn; `test_tools_matching_facets_ranking_by_matched_confidence` and `test_facet_match_detail_full_equality` must fail, then pass when restored.

---

### Task 3: Remove the reverted design

**Files:** `proxy/backend/models.py`, `proxy/backend/tool_facets.py`, `tests/proxy/test_tool_facets.py`

- Delete the `ToolSignalFacet` model and the `FACET_*` / `FACET_TYPES` / `ANALYZER_FACET_TYPES` constants introduced for it.
- Delete `extract_facets` and `replace_analyzer_facets` (their job now belongs to `_analyzer_facets` in the projection) and any tests specific to them.
- Grep the repo for every removed name and fix stragglers.
- The table was never deployed, so no migration or data cleanup is needed — confirm `tool_signal_facets` appears nowhere outside this branch's own history.

**Done when:** full suite green, ruff clean, and `grep -rn "ToolSignalFacet\|tool_signal_facets\|replace_analyzer_facets" proxy/ tests/` returns nothing.

---

### Task 4: Coverage and backfill verification (no new code expected)

The reverted design needed a bespoke backfill and an incremental hook. Both are now the existing pipeline's job. **Verify rather than build:**

1. Confirm `migrate.py:77` (`catalog_projection.refresh_candidates`) plus the hourly `catalog-projection` job (`jobs.yaml:110-116`) will converge every tool that has a report. Read `refresh_candidates` (`catalog_projection.py:459-483`) and check its candidate selection actually reaches tools whose only change is a NEW ANALYSIS REPORT — if candidate selection keys solely on catalog-record staleness, a scanned-but-otherwise-unchanged tool might never be reprojected. **If that gap exists, this task becomes real work:** extend candidate selection to include tools whose latest report is newer than their projection's `refreshed_at`, with a test.
2. Confirm `repository_scan.py:309`'s refresh call reaches `catalog_projection.refresh_tool_names` for the scanned tool, with a test asserting analyzer facets exist after a simulated scan.

**Done when:** both paths are demonstrated by tests, or the gap in (1) is closed and tested.

---

## Phase completion check

- Analyzer facets appear in `catalog_facet_values` after a projection refresh, with correct field names, casefolded values, preserved labels, converted confidences, and provenance.
- Declared facets are unaffected; malformed reports cannot cost a tool its declared facets.
- Query helpers answer "which tools use X" over the union vocabulary with all six pinned semantics intact, mutation checks re-verified after the retarget.
- No `ToolSignalFacet` remnants anywhere.
- Full suite green; coverage no worse than main's 91.22; ruff clean under the pinned version.
