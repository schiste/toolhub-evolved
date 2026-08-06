<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on any push in this range, so these were written by hand and checked against the commits. -->
<!-- Source range: 828438f..4fb37e2 (35 commits) -->

# Technical Release Notes

- Adds person-centric APIs, Evolved profile storage, and a unified relationship-claim workflow with evidence reconciliation over canonical Toolhub reads.
- Serves tool cards a projected health summary — score, grade and maintainer counts — instead of the whole record, and fetches the popover breakdown after the route has rendered.
- Persists health summaries in the browser, so a cached score paints with its card and revalidates in the background instead of arriving in a later repaint.
- Cuts the composed landing payload from about 340KB to about 82KB, and a card's summary from roughly 8KB to under 1KB.
- Splits backend/v1.py from 5,707 lines and 83 routes into fifteen per-family blueprints over a shared backend/v1_common; URL paths and methods are unchanged.
- Gzips static text assets at build time rather than once per request, which removed the compression cost from a CPU-capped pod.
- Clears every ruff finding across proxy/ with no new suppressions, and brings ruff format back to passing.
- Ignores a build-time gzipped twin older than the file it represents, so correcting a generated artifact in place is not silently overridden by the stale compressed copy.
