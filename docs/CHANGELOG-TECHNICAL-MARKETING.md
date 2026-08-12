<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on any push in this range, so these were written by hand and checked against the commits. -->
<!-- Release id: community-directory-identities -->
<!-- Release title: Community directory and connected identities -->
<!-- Source range: 828438f..90b98ad (184 commits) -->

# Technical Release Notes

- Replaces display-only public identities with a unified community projection over stable people, official accounts, canonical tools, contribution evidence, and unresolved attribution clusters; immutable Toolhub/Wikimedia IDs and verified Toolforge data drive reconciliation and conflict quarantine.
- Materializes typed relationship evidence with status, confidence, provenance, verification method/date, and viewer write context; public projections expose only author and maintainer roles while retaining record authority and catalog activity internally.
- Uses generation-based account synchronization, deterministic bounded reconciliation, actionable conflict review, compact paginated person-tool summaries, and first-class tool matches without browser request fan-out.
- Projects immutable Toolforge LDAP accounts and memberships into the canonical relationship graph, supports multiple verified accounts per person, and adds bounded single-use OpenSSH SSHSIG challenges for user-initiated account repair without creating a parallel relationship cache.
- Makes SPA navigation and refresh rendering convergent through normalized route identity, tracked/coalesced background repaints, view-specific summary batching, bounded reads and lazy imports, and separation of navigation cleanup from data refresh.
- Reduces landing/card payloads, persists projected health summaries, lazily loads full breakdowns, skips retired evidence backfills, precompresses static assets, and keeps cache/reconciliation failure modes bounded and recoverable; complete generation-validated catalog snapshots atomically retire absent tools and queue evidence withdrawal, scheduled jobs separate healthy no-ops from failures, and copy-truncate rotation caps uwsgi and per-job logs without detaching live writers.
- Consolidates the frontend around reusable catalog cards, Wikimedia-compatible localization, explicit accessibility/failure states, and regression coverage for large directories, identity trust, action authorization, history, RTL, keyboard focus, and loading settlement.
- Stages release manifests before restart, promotes them only after a successful smoke check, and groups repeated deployments under stable curated release IDs; legacy per-fix rows are retired and reviewed notes remain bounded to three to eight entries.
