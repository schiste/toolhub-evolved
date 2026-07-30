<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Hybrid Feature Realization Plan

This plan turns the feature-status inventory in `docs/FEATURES.md` into fully
backed Toolhub Evolved features.

The product model is deliberately hybrid:

- Toolhub remains the source of truth for official catalog records.
- Supported signed-in actions publish to official Toolhub first through
  `/v1/write/*` with the user's Toolhub OAuth grant.
- Evolved stores only complementary data: drafts, rejected-write fallbacks,
  local records, synthetic-to-real signals, media, activity rows, and sync
  metadata.
- Every Evolved-owned datum must carry provenance so the UI can distinguish
  official Toolhub data from Evolved-local data.
- Production launch requires a clean data surface: no fixtures, mock records,
  browser-local demo writes, deterministic fake metrics, or placeholder media
  may remain in the user-facing production experience.

## Current Backend Baseline

Implemented local tables in `proxy/backend/models.py`:

| Table                     | Purpose                                                | Toolhub equivalent                                                                     |
| ------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| `users`                   | Local record of a Toolhub OAuth user and Evolved role. | Toolhub `/api/user/` identity is official; local role gates Evolved-only data/actions. |
| `toolhub_tokens`          | Server-side official OAuth grant.                      | Toolhub owns authorization; Evolved stores grant secrets only server-side.             |
| `favorites`               | Per-user local favorite cache/fallback.                | Toolhub has official favorites.                                                        |
| `lists`                   | Per-user local draft/fallback lists.                   | Toolhub has official lists.                                                            |
| `tools`                   | Net-new Evolved tool records, never upstream mirrors.  | Toolhub has official tools; Evolved-local rows feed `/toolinfo.json`.                  |
| `tool_overlays`           | Evolved field patches for tool edits and annotations.  | Toolhub has official tool core fields and annotations.                                 |
| `activity`                | Evolved revision/audit rows for local actions.         | Toolhub has official recent/audit/history feeds.                                       |
| `crawler_urls`            | User-registered local crawler URLs.                    | Toolhub has official crawler URL registration.                                         |
| `crawler_runs`            | Server crawler run outcomes.                           | Toolhub has official crawler runs for official URLs.                                   |
| `toolinfo_discovery`      | Automated per-tool toolinfo.json discovery cache.      | Toolhub does not expose owner-facing root/sitemap toolinfo discovery state.            |
| `toolinfo_discovery_meta` | Discovery job cursor state.                            | Toolhub does not expose Evolved's local crawl cursor.                                  |
| `toolinfo_sources`        | Official crawler URL source evidence cache.            | Mirrors Toolhub `/api/crawler/urls/` registrations for provenance only.                |
| `toolinfo_source_items`   | Per-tool official feed source mapping.                 | Toolhub crawls this data but does not expose feed source per tool.                     |
| `tool_events`             | Privacy-limited Evolved interaction events.            | Toolhub does not expose Evolved-site usage events.                                     |
| `tool_thanks`             | Authenticated thanks on Evolved.                       | Toolhub does not expose thanks.                                                        |
| `tool_author_claims`      | Per-tool author-name verification evidence.            | Toolhub exposes display author fields but not Evolved verification state.              |
| `tool_author_keys`        | User-registered public keys for signed toolinfo proof. | Toolhub does not expose Evolved signed-toolinfo keys.                                  |
| `source_analysis_reports` | Redacted source-code metadata analysis reports.        | Toolhub does not infer access/project metadata from maintainer source code.            |
| `tool_health_*`           | Evolved health targets and observations.               | Toolhub does not expose tool health checks.                                            |
| `tool_media`              | URL-based screenshot/media metadata for review.        | Toolhub does not expose screenshots.                                                   |
| `api_cache`               | Anonymous official Toolhub API response cache.         | Performance cache only; Toolhub remains canonical.                                     |
| `api_cache_meta`          | Shared cache coordination metadata.                    | Poll markers and throttles only; safe to clear.                                        |
| `tool_owner_cache`        | Derived owner labels for `/recent` tool rows.          | Performance cache only; not canonical authorship or permission state.                  |

Backend endpoints already implemented:

- `GET /v1/user/`, `GET /v1/config/`, `GET /v1/overlay/`
- `PUT /v1/overlay/<key>` for `favorites`, `lists`, `crawlerUrls`,
  `toolNew`, `toolEdits`, `toolAnnos`, `revisions`, `auditlogs`
- `/v1/write/*` lifecycle for official-first tools, annotations, lists,
  favorites, and crawler URL writes; `/v1/toolhub/*` remains as a lower-level
  compatibility bridge
- `POST /v1/write/tools/` also accepts an optional create-only `toolinfo_url`;
  Evolved fetches it once with the crawler safety rules, fills missing optional
  create fields, records local crawler/signed-toolinfo evidence, and still sends
  the canonical create to official Toolhub first
- `GET /v1/me/tools/` resolver for signed-in users, combining official Toolhub
  author search with Evolved-local `tool_author_claims` verification signals
  and indexed official crawler source evidence
- `GET|POST /v1/author-keys/`, `DELETE /v1/author-keys/<key_id>/`, and
  `POST /v1/toolinfo/signing-payload/` for signed-toolinfo public-key
  registration and canonical signing payload generation
- `GET|POST /v1/source-analysis/`, `GET /v1/source-analysis/<id>/`, and
  `POST /v1/source-analysis/<id>/review/` for owner-private source-code
  metadata suggestions and maintainer review
- `GET /v1/search/tools/` for Evolved-local tools
- `GET /v1/recent/owners/` for bulk owner-by-tool enrichment on `/recent`,
  backed by the shared `tool_owner_cache`
- `GET /v1/tools/<name>/signals/`, `POST /v1/tools/<name>/events/`,
  `POST|DELETE /v1/tools/<name>/thanks/`
- `PUT /v1/tools/<name>/health-target/`
- `GET|POST /v1/tools/<name>/media/`, `DELETE /v1/media/<id>/`
- `GET /v1/moderation/public-data/` and
  `PUT /v1/moderation/public-data/<kind>/<id>/` for Evolved-only reviewer
  approval/rejection of public local data
- `GET /v1/crawler/runs/`, `GET /v1/user/export/`,
  `DELETE /v1/user/evolved-data/`
- `GET /toolinfo.json` for feeding Evolved-local tools into official Toolhub

Author verification now uses provider-specific evidence rows rather than
treating Toolhub author display names as proof. `AuthorNameProvider` records
display-name matches as unverified candidates; `ToolforgeMembershipProvider`
discovers Toolforge `tools.*` memberships through public LDAP so Evolved can
fetch exact official `toolforge-*` Toolhub records; `ToolforgeMaintainerProvider`
checks public Toolsadmin maintainer pages; `ToolhubWriteProvider` records
verification after a successful official Toolhub tool write by the same user;
and `SignedToolinfoProvider` verifies signed `toolinfo.json` records against
active `tool_author_keys` public keys. These claims improve Evolved provenance
and "My tools" discovery only; they never become official Toolhub permissions or
canonical Toolhub authorship. Verification is strictly per tool: a verified
claim for `Christophe` on one `tool_name` does not verify `Christophe` on any
other tool unless that other tool has its own verified claim row.

## Cross-Cutting Work First

These are prerequisites before expanding any feature deeply.

1. **Provenance and sync status**
    - Status: implemented baseline in `backend.sync` and the `/v1` overlay
      write/read paths.
    - Shared sync vocabulary: `official`, `local_draft`, `local_fallback`,
      `evolved_real`, `sync_error`.
    - Store `official_id` or `official_name` where Toolhub returns one.
    - Store `sync_status`, `last_synced_at`, `last_error`, `source`, and
      `created_by_user_id` where relevant to Evolved-owned local records.
    - Store `deleted_at` for soft-deleted records and `review_status` for
      public Evolved-owned records such as local tools, health targets, thanks,
      and media.
    - Canonical data rule: local new-tool records only fill in after a live
      Toolhub 404, and local overlays cannot persist or apply canonical
      identity fields such as `name` and `origin`.
    - UI rule: official data has no warning; local Evolved data is labeled
      near the affected field, not only in page-level copy.

2. **Evolved-local authorization**
    - Keep Toolhub OAuth as the only sign-in path and continue mapping
      `GET /api/user/` into local `users`.
    - Store the Evolved-only role on `users.role`: `user`, `reviewer`, or
      `admin`.
    - Route all Evolved-owned backend reads/writes through
      `backend.authz.can(user, action, resource)`.
    - Enforce ownership for private local data: drafts, overlays, fallback
      lists/favorites, crawler URLs, thanks, health targets, and submitted
      media.
    - Keep elevated roles local to Evolved. They can unlock Evolved moderation
      or operator actions, but they never imply special rights on official
      Toolhub; official writes still succeed or fail through Toolhub's API.

3. **Local object lifecycle**
    - Status: implemented baseline for current write families through
      `/v1/write/*`.
    - Add common created/updated/deleted timestamps and soft-delete where useful.
    - Add "retry official publish" actions for fallback records.
    - Add account-level export/delete for Evolved-owned data.

4. **Activity taxonomy**
    - Status: structured backend rows are emitted by the official-first write
      lifecycle while legacy feed shapes remain available to the SPA.
    - Replace generic activity rows with structured rows:
      `kind`, `object_type`, `object_key`, `action`, `actor_user_id`,
      `official_status`, `payload`, `created_at`.
    - Feed pages should merge live Toolhub rows plus Evolved rows with labels.

5. **Abuse controls**
    - Status: implemented baseline for signed-in write guards, per-user rate
      limiting, public-data review states, and reviewer approval/rejection.
    - Expand rate limits to include IP hash and per-action buckets.
    - Keep moderation flags for public Evolved-only records, health targets,
      media, and thanks.
    - Keep OAuth tokens encrypted or otherwise protected at rest before broader
      production use.

6. **Production cleanliness**
    - Inventory every fixture, mock helper, deterministic synthetic generator,
      placeholder asset, and browser-local demo write path.
    - Remove them from the production bundle or guard them so they are available
      only in tests/local development, never on Toolforge production.
    - Replace synthetic metrics with real Evolved-owned backend data before
      showing them in production; if the real source is not ready, remove or
      hide the feature instead of shipping fake numbers.
    - Remove signed-out mutation flows. Signed-out users can read live Toolhub
      data; any create/update/delete action must require Toolhub sign-in.
    - Add CI checks that fail on production-facing "mock", "fixture", "demo
      data", placeholder media, and deterministic metric paths outside
      test/dev-only files.

7. **Docs and issue hygiene**
    - Status: parent epic created as GitHub issue #102, with feature-area child
      issues #103 through #109.
    - Keep this plan, `docs/PRODUCTION.md`, and `docs/RUNBOOK.md` in sync
      whenever a local table, trust boundary, write lifecycle, review queue, or
      production-cleanliness rule changes.
    - Keep the GitHub issue tracker on the production hybrid vocabulary:
      "Toolhub-first write", "Evolved-local backend overlay", "fallback",
      "draft", "review", and "provenance". Do not reintroduce removed
      experimental-toggle or browser-local demo wording for production work.
    - Attach new implementation issues to the parent epic through a linked
      checklist item and a `Parent epic: #102` back link in the child issue.

## Feature-By-Feature Plan

### 1. Toolhub Sign-In

Current: official Toolhub OAuth plus an Evolved server session.

Make it fully real:

- Keep Toolhub OAuth as the only login path.
- Use `GET /api/user/` after OAuth to refresh the local username and Toolhub
  user id on every login.
- Add a user settings page for Evolved data export, local-data deletion, and
  OAuth reconnect.
- Store grant metadata: `scope`, `expires_at`, `last_validated_at`,
  `last_failure_at`.

Evolved-only backend data:

- `users`
- `toolhub_tokens`
- planned `user_settings`
- planned `user_data_exports`

### 2. Reset Demo Data

Current: clears browser-local demo keys.

Make it fully real:

- Remove "Reset demo data" from production because production must not create
  demo data.
- Keep any fixture reset helper only in local development or tests.
- Add signed-in production account/data actions:
    - clear browser cache and pull fresh server overlay;
    - delete selected Evolved-local data from the server;
    - disconnect Toolhub OAuth.
- Never delete official Toolhub data through this control.

Evolved-only backend data:

- none for signed-out reset
- planned deletion jobs/audit rows for signed-in Evolved data deletion

### 3. Favorites

Current: signed-in changes write to Toolhub favorites; signed-out demo mode
stores names locally.

Make it fully real:

- Remove signed-out favorite writes from production; prompt users to sign in
  with Toolhub instead.
- Treat official Toolhub favorite state as canonical after a successful write.
- Keep `favorites` as a local optimistic cache and offline/error fallback.
- Pull official favorites on login where Toolhub exposes them; reconcile with
  local cache by preferring official state.
- Add visible retry/error state if official add/delete fails.

Evolved-only backend data:

- `favorites` as cache/fallback only
- planned `favorite_sync_events` or generic structured `activity`

### 4. Lists

Current: official create/edit/delete when permitted; local draft lists remain as
fallback.

Make it fully real:

- Store Toolhub's official list id when create succeeds.
- Split local list states:
    - official-backed list cache;
    - Evolved draft list not yet published;
    - fallback list after official rejection.
- Add "Publish to Toolhub", "Retry publish", and "Keep local" decisions.
- Merge official lists and local lists with provenance labels in `/lists` and
  `/my-lists`.

Evolved-only backend data:

- `lists`
- columns: `official_list_id`, `source`, `sync_status`, `last_synced_at`,
  `last_error`, `created_by_user_id`, `deleted_at`
- structured list activity rows

### 5. Submit A Tool

Current: official `POST /api/tools/` first; rejected submissions become local
Evolved drafts.

Make it fully real:

- Validate locally against the Toolhub tool schema before attempting official
  create.
- Allow a create-only `toolinfo_url` so Evolved can fetch the maintainer's
  `toolinfo.json` immediately, fill missing optional fields before the official
  Toolhub create, and keep the URL registered locally for future scheduled
  crawler refreshes.
- Store full official-write response, validation errors, and local draft state.
- For Evolved-local drafts, expose:
    - private draft view;
    - public local record when the user chooses to publish locally;
    - `/toolinfo.json` feed entry so official Toolhub can ingest accepted local
      records later.
- Add admin/moderation controls for public Evolved-local records.

Evolved-only backend data:

- `tools`
- columns: `visibility`, `source`, `sync_status`, `official_name`,
  `validation_errors`, `last_toolhub_response`, `created_by_user_id`,
  `review_status`, `deleted_at`
- planned `tool_publication_attempts`
- structured activity rows

### 6. Edit A Tool

Current: official `PUT` when Toolhub permits; rejected edits remain local
overlays.

Make it fully real:

- Add per-field overlay provenance, not just per-tool overlay state.
- Track the live Toolhub revision or modified timestamp the edit was based on.
- If official update fails due to permissions, keep the Evolved overlay as a
  suggested edit and show it as local.
- Add a maintainer/admin flow to accept, discard, or retry local overlays.

Evolved-only backend data:

- `tool_overlays` with `kind = edits`
- columns: `base_revision`, `field_statuses`, `source`, `sync_status`,
  `last_synced_at`, `last_error`, `created_by_user_id`, `review_status`,
  `deleted_at`
- planned `overlay_reviews`

### 7. Edit Annotations

Current: official annotation `PUT` first; rejected annotations remain local
overlays.

Make it fully real:

- Keep official Toolhub annotations canonical when write succeeds.
- Store local annotation overlays by field when rejected or draft-only.
- Display merged official-plus-local annotations with per-field labels.
- Add review/retry handling matching core edits.

Evolved-only backend data:

- `tool_overlays` with `kind = annos`
- same sync/review columns as edit overlays

### 8. Add / Remove Tools (Crawler)

Current: signed-in URL registrations write to Toolhub; pasted JSON ingestion
remains local to Evolved.

Make it fully real:

- Store official crawler URL id after successful Toolhub registration.
- Keep Evolved-local crawler URLs for sources that cannot be registered
  officially or are intentionally local.
- Let Add/remove tools accept a homepage by discovering the origin
  `/toolinfo.json` first and same-origin `sitemap.xml` toolinfo entries only
  after a root `404`; store/register only the discovered concrete
  `toolinfo.json` URL.
- Cache automated root/sitemap discovery for official Toolhub tools by walking
  `/api/tools/` with a persistent cursor, while `/v1/me/tools/` also seeds rows
  for immediately owner-visible matches. My tools can then show
  found/missing/pending/error/no-URL state without manual URL entry.
- Mirror official `/api/crawler/urls/`, fetch each registered feed out of band,
  and store `toolinfo_sources`/`toolinfo_source_items` so My tools can show the
  official feed that declared a tool (Toolsadmin, user-script aggregate, wiki
  raw feed, GitHub raw JSON, self-hosted toolinfo, or other registered feed).
- Run the server-side crawler job on local URLs, validate toolinfo, and upsert
  `tools` records without mirroring official Toolhub tools.
- Reuse the same hardened fetch path during tool creation when a user supplies a
  `toolinfo_url`; failed create-time fetches are stored as local `sync_error`
  crawler rows so the scheduled crawler can retry and surface the error.
- Surface crawler run history with per-URL errors and official/local labels.
- Publish Evolved-local accepted tools through `/toolinfo.json`.

Evolved-only backend data:

- `crawler_urls`
- `crawler_runs`
- `tools`
- crawler URL columns: `official_crawler_url_id`, `source`, `enabled`,
  `sync_status`, `last_synced_at`, `last_checked_at`, `last_status`,
  `last_error`, `created_by_user_id`

### 9. Activity Feeds

Current: local revision/audit rows merge on top of live feeds.

Make it fully real:

- Convert local feed rows into structured events generated server-side for all
  Evolved writes.
- Merge live Toolhub recent/audit/history rows with Evolved activity on the
  relevant pages.
- Link every Evolved event to its object and provenance.
- Add filters for official Toolhub vs Evolved-local activity.

Evolved-only backend data:

- `activity`
- planned structured event fields listed in "Activity taxonomy"

### 10. Popularity

Current: deterministic pseudo-random number derived from tool name.

Make it fully real:

- Remove deterministic synthetic counts from production.
- Replace them with Evolved-owned aggregate metrics.
- Count privacy-preserving interactions on this site:
    - tool detail views;
    - search result clicks;
    - favorite/list additions;
    - outbound tool URL clicks.
- Publish labels as "popular on Evolved" unless an official Toolhub usage source
  becomes available.
- Keep raw events short-lived; store daily aggregates long-term.

Evolved-only backend data:

- planned `tool_events` with short retention
- planned `tool_metric_daily` aggregate table
- planned `tool_metric_totals` materialized view/cache

### 11. Operational Health

Current: signed-in users can submit Evolved health targets; public signals show
only approved Evolved health records and never label them as Toolhub data.

Make it fully real:

- Keep deterministic health states out of production.
- Keep health target models separate from official Toolhub data.
- Keep maintainer/user-provided health URLs pending until Evolved reviewer
  approval.
- Run scheduled checks with conservative timeout/rate limits.
- Store observations and expose a recent aggregate: healthy, degraded, down, or
  unknown.
- Show the checked URL/source, Evolved data label, review state, and last
  checked time.

Evolved-only backend data:

- `tool_health_targets`
- `tool_health_checks`
- planned `tool_health_daily`

### 12. Thanks

Current: signed-in users can thank a tool; approved counts are stored in
Evolved, labeled as Evolved data, and filter out rejected/pending rows.

Make it fully real:

- Keep deterministic thanks counts out of production.
- Keep authenticated "thanks" events stored in Evolved.
- Keep one active thanks per user/tool, with optional undo.
- Aggregate counts per tool and show "thanks on Evolved".
- Add deeper abuse controls: self-thanks handling, suspicious-burst detection,
  and daily aggregate rollups.

Evolved-only backend data:

- `tool_thanks`
- planned `tool_thanks_daily`
- planned structured activity rows for thanks add/remove events

### 13. 30-Day Usage

Current: deterministic per-tool usage number.

Make it fully real:

- Remove deterministic usage numbers from production.
- Reframe the metric as "30-day Evolved usage" unless an official source is
  later provided.
- Use the same privacy-preserving event stream as popularity.
- Show only aggregates above a minimum threshold to avoid exposing tiny-user
  behavior.
- Consider separate metrics for views, launches/outbound clicks, and saves.

Evolved-only backend data:

- planned `tool_events`
- planned `tool_metric_daily`
- planned minimum-count suppression policy

### 14. Screenshots

Current: signed-in users can submit URL-based screenshots with license/source
metadata; approved Evolved media records render on tool pages with Evolved data
labels.

Make it fully real:

- Keep placeholder screenshot strips out of production.
- Keep media records for screenshots owned by Evolved, not Toolhub.
- Support upload or URL-based capture only with explicit license/source fields.
- Store files on Toolforge storage or another approved Wikimedia-compatible
  storage path; store only metadata in ToolsDB.
- Keep moderation and deletion before screenshots are public.
- Show provenance, license, uploader, and capture/upload date.

Evolved-only backend data:

- `tool_media`
- planned `tool_media_files`
- reviewer decisions through `activity` rows

## Implementation Phases

### Phase 0: Data Contract Hardening

- Remove or test/dev-guard all production-facing fixtures, mock data, demo write
  paths, deterministic metrics, and placeholder media.
- Add a CI cleanliness check that blocks new production-facing fixture/mock/demo
  data.
- Add the Evolved-local role/policy foundation: `users.role`,
  `backend.authz.can(user, action, resource)`, env-based reviewer/admin
  bootstrap, and route-level ownership checks for private Evolved data.
- Add provenance and sync-status columns to existing local tables.
- Add structured activity events and migrate existing `activity` rows if needed.
- Add the Evolved-only public-data moderation endpoint for local tool records,
  health targets, thanks, and media.
- Keep the backend data register in `docs/RUNBOOK.md` current.
- Add tests proving local records never overwrite official Toolhub data.

### Phase 1: Official-First Contribution Features

- Status: implemented baseline official-first write lifecycle, retry/discard
  endpoints, and shared UI status components for tool core fields,
  annotations, lists, and crawler URLs.
- Finish favorites reconciliation against official state.
- Add official id/sync status for lists.
- Add official response capture and retry actions for tools, edits, annotations,
  and crawler URLs.
- Make all local fallback states visible in the UI.
- Keep field-level provenance labels on every create/edit surface that can mix
  live Toolhub data with Evolved-local overlays.

### Phase 2: Local Catalog And Crawler

- Complete local crawler run UI from `crawler_runs`.
- Add local record moderation/publication controls.
- Strengthen `/toolinfo.json` feed documentation and validation.
- Add federated search provenance and local facet counts.

### Phase 3: Activity, Audit, And User Data Controls

- Generate all Evolved activity server-side.
- Add official/Evolved filters on recent changes, audit logs, and histories.
- Add export/delete flows for Evolved-owned data.
- Add admin audit views for local moderation actions.

### Phase 4: Real Signals

- Status: implemented baseline for real Evolved events, thanks, health-target
  submission, public review states, and Evolved data labels.
- Implement event collection with privacy constraints.
- Replace synthetic popularity and 30-day usage with aggregates, or keep the
  features hidden until real aggregates exist.
- Expand thanks events into daily aggregate counts.
- Add scheduled health checks and daily health rollups.

### Phase 5: Media

- Status: implemented baseline for URL metadata, license/source capture,
  reviewer approval, deletion, and Evolved data labels.
- Add durable upload/storage.
- Replace any remaining placeholder screenshots with real Evolved-owned media.

### Phase 6: Docs And Issue Hygiene

- Status: created the hybrid foundation parent epic (#102) and child tracking
  issues for identity (#103), UI contract (#104), write lifecycle (#105),
  provenance (#106), docs hygiene (#107), production cleanliness (#108), and
  Evolved-only public data controls (#109).
- Refresh open imported feature issues whenever their wording still describes
  removed experimental-toggle flows, browser-local demo writes, browser-only
  simulations, or Lane B as a separate demo surface.
- Keep issue labels aligned with the production model; `lane-b` now means the
  prospective hybrid Evolved roadmap rather than a toggle.
- Treat issue hygiene as part of feature readiness: a feature is not ready for
  broad work if its docs and tracking issue disagree about canonical Toolhub
  data, local Evolved data, or write authority.

## Documentation Requirements For Every New Backend Feature

Every backend feature that is not official Toolhub data must update:

- `docs/HYBRID-FEATURE-PLAN.md`: feature status, owned tables, and rollout
  phase.
- `docs/RUNBOOK.md`: operational setup, env vars, jobs, backup/restore, and
  failure modes.
- `docs/PRODUCTION.md`: architecture impact if a new class of data or trust
  boundary is introduced.
- `docs/FEATURES.md`: indirectly, by changing `EXPERIMENTS` in
  `public_html/views/experiments.js` and running `npm run features:docs`.
- GitHub issues: update parent epic #102 or the relevant child issue so the
  implementation status and open follow-up work are discoverable.
- UI copy: provenance labels and Rules of Engagement language when users can
  create or expose new Evolved-owned data.

Minimum documentation for each Evolved-owned table:

- owner and purpose;
- whether rows are public, private, or admin-only;
- retention/deletion behavior;
- whether it can be exported by the user;
- whether it can be fed back to official Toolhub;
- abuse/moderation controls;
- backup/restore notes.
