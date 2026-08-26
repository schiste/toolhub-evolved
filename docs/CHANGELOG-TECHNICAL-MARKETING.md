<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: reading-only-what-it-needs -->
<!-- Release title: Reading Only What It Needs -->
<!-- Source range: f55d94aa..9a980b2b (1 commit) -->

# Technical and Marketing Notes

- Five whole-entity scans across three jobs now select only the columns their loops read. `catalog_validation._candidate_rows` takes `tool_name`, `effective_record` and `validation`; `tool_assets.refresh_candidates` takes those first two plus `provenance` from the projection and four scalars from `ToolAssetCache`; `graph_enrichment.refresh_candidates` takes `tool_name` and `record` from `CanonicalToolCache` and four scalars from `GraphToolEnrichment`; `status_summary` takes two.
- The three scans that still carry a JSON payload stream at `yield_per=500` rather than materializing. Narrowing alone would have fixed the current numbers while leaving peak memory proportional to the table, so the next growth step would have reproduced the outage; batching bounds it regardless of catalogue size. Same pattern `catalog_statistics._stream` already used.
- Loop bodies are unchanged: a SQLAlchemy `Row` exposes attribute access by column name. `_icon_source` is typed loosely because `refresh_candidates` now hands it a two-column `Row` instead of the entity, and `status_summary` increments a counter as it streams instead of measuring a materialized list. `merge_cached_records` was left alone; it is already bounded by an explicit name list.
- Three cost-regression tests attach a `before_cursor_execute` listener and assert the emitted SQL never names the columns each scan does not use. All three fail against the pre-change sources and pass after, checked by restoring the previous files from git rather than by inspection.
- A fourth test pins that narrowing `tool_assets` did not change who is judged due: one tool per branch of the eligibility check, including a deferred error that must be skipped. Each branch keys off a different column, so a select that dropped one would still return rows, just the wrong ones, silently.
- The `mem: 2Gi` lines from the previous release stay. They come out in a follow-up once the rewritten jobs are observed inside the 512Mi default in production, not on the assumption that they fit.
- This completes the defect class opened in `0f7a1ac4`, where session 165 gave `catalog_projection.refresh_candidates` the same treatment. Four call sites in this codebase have now scaled memory with the catalogue; the measured cause is recorded at each one so the next reader does not re-derive it.
- Validation: full proxy suite 3300 passed, 25 skipped locally; `ruff check` and `ruff format` clean on `proxy/`. Broker gates `jscpd-python`, `ruff-check`, `ruff-format`, `cspell`, `prettier` and `pytest-proxy` all passed on tree `aed5338b1fae`.
