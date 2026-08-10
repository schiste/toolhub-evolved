<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on any push in this range, so these were written by hand and checked against the commits. -->
<!-- Source range: 828438f..e069940 (113 commits) -->

# Technical Release Notes

- Adds a unified `/v1/community/` projection over stable people, official accounts, catalog evidence, and unresolved attributions, with deterministic ranking, typed filters, real counts, pagination, and explicit canonical-authority metadata.
- Reconciles structured Toolhub wiki handles when they exactly match the canonical CentralAuth username behind an immutable global user id, while keeping Toolforge membership and Toolhub write authority as separate claims.
- Adds a resumable generation-based official Toolhub account projection; incomplete or count-mismatched refreshes cannot replace the last complete generation, and deploys require a complete refresh before restart.
- Materializes stable people from immutable Toolhub and Wikimedia global user ids, reconciles SUL-backed Toolforge identities without OAuth participation, and refreshes public links after account synchronization.
- Adds deterministic dry-run/apply reconciliation, bounded identity batches, durable candidate/conflict review, stable-id conflict quarantine, and incremental changed-tool queue processing.
- Replaces browser-side profile request fan-out with server-paginated compact tool summaries and clamps public page sizes.
- Exposes relationship status, confidence, evidence source/count, authority, verification method/date, viewer-specific write context, and per-role total/verified tool counts without conflating identity and relationship verification.
- Aligns community search with the catalog `browse`, `facets`, and `tcard` primitives and adds a reusable escaped entity-card adapter with metric, evidence, and trust-signal slots.
- Moves frontend messages to Wikimedia Banana format, validates extracted English and qqq catalogs, serves missing locales correctly, and keeps the production JavaScript budget within its ratchet.
- Adds regression coverage for 2,000-plus account pagination, interrupted synchronization, stable cross-links, contributor eligibility, directory history, prolific profiles, trust labels, action authorization boundaries, and linked-account relationship metrics.
- Makes conflict recording tolerant of historical duplicate pending rows, preserves one canonical pending review item, dismisses redundant queue entries with an audit note, and reports the consolidation count.
- Treats a failed explicit MariaDB `RELEASE_LOCK` after successful long-running work as connection cleanup rather than job failure; connection-scoped locks are already released when the server resets that connection.
- Replaces the 50-result, first-match legacy author resolver with a server-side exact-handle decision API and explicit frontend disambiguation for display names, handle collisions, and unresolved labels.
- Stops publishing display-only attribution records as people, aggregates them by label, and keeps their per-source identity scopes intact.
- Adds Toolhub and Wikimedia stable identifiers, correctly namespaces Toolforge developer handles, and persists authenticated LDAP membership evidence without treating access as authorship.
- Adds bounded exact-Toolhub identity discovery, durable approve/reject/split review decisions, stable-id conflict quarantine, and automatic reapplication after catalog refreshes.
- Adds person-centric APIs, Evolved profile storage, and a unified relationship-claim workflow with evidence reconciliation over canonical Toolhub reads.
- Serves tool cards a projected health summary — score, grade and maintainer counts — instead of the whole record, and fetches the popover breakdown after the route has rendered.
- Persists health summaries in the browser, so a cached score paints with its card and revalidates in the background instead of arriving in a later repaint.
- Cuts the composed landing payload from about 340KB to about 82KB, and a card's summary from roughly 8KB to under 1KB.
- Splits backend/v1.py from 5,707 lines and 83 routes into fifteen per-family blueprints over a shared backend/v1_common; URL paths and methods are unchanged.
- Gzips static text assets at build time rather than once per request, which removed the compression cost from a CPU-capped pod.
- Clears every ruff finding across proxy/ with no new suppressions, and brings ruff format back to passing.
- Ignores a build-time gzipped twin older than the file it represents, so correcting a generated artifact in place is not silently overridden by the stale compressed copy.
- Fails the push when the checked-in release notes do not describe the commits being pushed, which is how they went unnoticed for 34 commits while the hook reported them as skipped.
- Ignores output/, where Playwright runs leave screenshots and storage-state files containing the signed-in session's cookies.
