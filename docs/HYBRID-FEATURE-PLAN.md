<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Hybrid Feature Realization Plan

This plan turns the feature-status inventory in `docs/FEATURES.md` into fully
backed Toolhub Evolved features.

The product model is deliberately hybrid:

- Toolhub remains the source of truth for official catalog records.
- Supported signed-in actions publish to official Toolhub first through
  `/v1/toolhub/*` with the user's Toolhub OAuth grant.
- Evolved stores only complementary data: drafts, rejected-write fallbacks,
  local records, synthetic-to-real signals, media, activity rows, and sync
  metadata.
- Every Evolved-owned datum must carry provenance so the UI can distinguish
  official Toolhub data from Evolved-local data.

## Current Backend Baseline

Implemented local tables in `proxy/backend/models.py`:

| Table            | Purpose                                               | Toolhub equivalent                                                            |
| ---------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------- |
| `users`          | Local record of a Toolhub OAuth user.                 | Toolhub `/api/user/` identity is official; local row maps it to Evolved data. |
| `toolhub_tokens` | Server-side official OAuth grant.                     | Toolhub owns authorization; Evolved stores grant secrets only server-side.    |
| `favorites`      | Per-user local favorite cache/fallback.               | Toolhub has official favorites.                                               |
| `lists`          | Per-user local draft/fallback lists.                  | Toolhub has official lists.                                                   |
| `tools`          | Net-new Evolved tool records, never upstream mirrors. | Toolhub has official tools; Evolved-local rows feed `/toolinfo.json`.         |
| `tool_overlays`  | Evolved field patches for tool edits and annotations. | Toolhub has official tool core fields and annotations.                        |
| `activity`       | Evolved revision/audit rows for local actions.        | Toolhub has official recent/audit/history feeds.                              |
| `crawler_urls`   | User-registered local crawler URLs.                   | Toolhub has official crawler URL registration.                                |
| `crawler_runs`   | Server crawler run outcomes.                          | Toolhub has official crawler runs for official URLs.                          |

Backend endpoints already implemented:

- `GET /v1/user/`, `GET /v1/config/`, `GET /v1/overlay/`
- `PUT /v1/overlay/<key>` for `favorites`, `lists`, `crawlerUrls`,
  `toolNew`, `toolEdits`, `toolAnnos`, `revisions`, `auditlogs`
- `/v1/toolhub/*` bridge for official tools, annotations, lists, favorites, and
  crawler URL writes
- `GET /v1/search/tools/` for Evolved-local tools
- `GET /toolinfo.json` for feeding Evolved-local tools into official Toolhub

## Cross-Cutting Work First

These are prerequisites before expanding any feature deeply.

1. **Provenance and sync status**
    - Add a shared status vocabulary: `official`, `local_draft`,
      `local_fallback`, `synthetic`, `evolved_real`, `sync_error`.
    - Store `official_id` or `official_name` where Toolhub returns one.
    - Store `sync_status`, `last_synced_at`, `last_error`, and `source` on every
      local record that can be published to Toolhub.
    - UI rule: official data has no warning; local or synthetic data is labeled
      near the affected field, not only in page-level copy.

2. **Local object lifecycle**
    - Add common created/updated/deleted timestamps and soft-delete where useful.
    - Add "retry official publish" actions for fallback records.
    - Add account-level export/delete for Evolved-owned data.

3. **Activity taxonomy**
    - Replace generic activity rows with structured rows:
      `kind`, `object_type`, `object_key`, `action`, `actor_user_id`,
      `official_status`, `payload`, `created_at`.
    - Feed pages should merge live Toolhub rows plus Evolved rows with labels.

4. **Abuse controls**
    - Rate-limit write-heavy local features by user, IP hash, and action.
    - Add moderation flags for public Evolved-only records, media, and thanks.
    - Keep OAuth tokens encrypted or otherwise protected at rest before broader
      production use.

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

- Keep "Reset demo data" for signed-out browser-local mode.
- Add separate signed-in actions:
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
- planned columns: `official_list_id`, `source`, `sync_status`,
  `last_synced_at`, `last_error`, `deleted_at`
- structured list activity rows

### 5. Submit A Tool

Current: official `POST /api/tools/` first; rejected submissions become local
Evolved drafts.

Make it fully real:

- Validate locally against the Toolhub tool schema before attempting official
  create.
- Store full official-write response, validation errors, and local draft state.
- For Evolved-local drafts, expose:
    - private draft view;
    - public local record when the user chooses to publish locally;
    - `/toolinfo.json` feed entry so official Toolhub can ingest accepted local
      records later.
- Add admin/moderation controls for public Evolved-local records.

Evolved-only backend data:

- `tools`
- planned columns: `visibility`, `sync_status`, `official_name`,
  `validation_errors`, `last_toolhub_response`, `deleted_at`
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
- planned columns: `base_revision`, `field_statuses`, `sync_status`,
  `last_error`, `review_status`
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
- planned same sync/review columns as edit overlays

### 8. Add / Remove Tools (Crawler)

Current: signed-in URL registrations write to Toolhub; pasted JSON ingestion
remains local to Evolved.

Make it fully real:

- Store official crawler URL id after successful Toolhub registration.
- Keep Evolved-local crawler URLs for sources that cannot be registered
  officially or are intentionally local.
- Run the server-side crawler job on local URLs, validate toolinfo, and upsert
  `tools` records without mirroring official Toolhub tools.
- Surface crawler run history with per-URL errors and official/local labels.
- Publish Evolved-local accepted tools through `/toolinfo.json`.

Evolved-only backend data:

- `crawler_urls`
- `crawler_runs`
- `tools`
- planned columns: `official_crawler_url_id`, `source`, `enabled`,
  `last_checked_at`, `last_status`, `last_error`

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

- Replace synthetic counts with Evolved-owned aggregate metrics.
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

Current: deterministic health pill per tool.

Make it fully real:

- Add a health target model separate from official Toolhub data.
- Default target can be the tool URL, but support maintainer-provided health
  URLs in Evolved.
- Run scheduled checks with conservative timeout/rate limits.
- Store observations and expose a recent aggregate: healthy, degraded, down, or
  unknown.
- Show the checked URL/source and last checked time.

Evolved-only backend data:

- planned `tool_health_targets`
- planned `tool_health_checks`
- planned `tool_health_daily`

### 12. Thanks

Current: deterministic thanks count per tool.

Make it fully real:

- Add authenticated "thanks" events stored in Evolved.
- Enforce one active thanks per user/tool, with optional undo.
- Aggregate counts per tool and show "thanks on Evolved".
- Add abuse controls: rate limits, self-thanks handling, and moderation for
  suspicious bursts.

Evolved-only backend data:

- planned `tool_thanks`
- planned `tool_thanks_daily`
- structured activity rows for thanks add/remove events

### 13. 30-Day Usage

Current: deterministic per-tool usage number.

Make it fully real:

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

Current: static placeholder strip.

Make it fully real:

- Add media records for screenshots owned by Evolved, not Toolhub.
- Support upload or URL-based capture only with explicit license/source fields.
- Store files on Toolforge storage or another approved Wikimedia-compatible
  storage path; store only metadata in ToolsDB.
- Add moderation and deletion before screenshots are public.
- Show provenance, license, uploader, and capture/upload date.

Evolved-only backend data:

- planned `tool_media`
- planned `tool_media_files`
- planned `media_reviews`

## Implementation Phases

### Phase 0: Data Contract Hardening

- Add provenance and sync-status columns to existing local tables.
- Add structured activity events and migrate existing `activity` rows if needed.
- Keep the backend data register in `docs/RUNBOOK.md` current.
- Add tests proving local records never overwrite official Toolhub data.

### Phase 1: Official-First Contribution Features

- Finish favorites reconciliation against official state.
- Add official id/sync status for lists.
- Add official response capture and retry actions for tools, edits, annotations,
  and crawler URLs.
- Make all local fallback states visible in the UI.

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

- Implement event collection with privacy constraints.
- Replace synthetic popularity and 30-day usage with aggregates.
- Add thanks events and aggregate counts.
- Add health targets/checks and replace deterministic health.

### Phase 5: Media

- Add screenshot metadata and storage.
- Add moderation, licensing, and deletion flows.
- Replace placeholder screenshots with real Evolved-owned media.

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
