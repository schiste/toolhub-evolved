<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on any push in this range, so these were written by hand and checked against the commits. -->
<!-- Source range: 828438f..91a2807 (143 commits) -->

# Technical Release Notes

- Replaces display-only public identities with a unified community projection over stable people, official accounts, canonical tools, contribution evidence, and unresolved attribution clusters; immutable Toolhub/Wikimedia IDs and verified Toolforge data drive reconciliation and conflict quarantine.
- Materializes typed relationship evidence with status, confidence, provenance, authority, verification method/date, viewer write context, and per-role totals; legacy author resolution is server-side, stable-handle-only, and explicitly disambiguated.
- Uses generation-based account synchronization, deterministic bounded reconciliation, actionable conflict review, compact paginated person-tool summaries, and first-class tool matches without browser request fan-out.
- Makes SPA navigation and refresh rendering convergent through normalized route identity, tracked/coalesced background repaints, view-specific summary batching, bounded reads and lazy imports, and separation of navigation cleanup from data refresh.
- Reduces landing/card payloads, persists projected health summaries, lazily loads full breakdowns, skips retired evidence backfills, precompresses static assets, and keeps cache/reconciliation failure modes bounded and recoverable.
- Consolidates the frontend around reusable catalog cards, Wikimedia-compatible localization, explicit accessibility/failure states, and regression coverage for large directories, identity trust, action authorization, history, RTL, keyboard focus, and loading settlement.
- Stages release manifests before restart, promotes deployment history only after a successful smoke check, retains a bounded full release history, and validates reviewed release notes as three to eight bundled entries.
