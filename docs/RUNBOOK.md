<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Runbook — operating Toolhub Evolved in production

Companion to [`PRODUCTION.md`](PRODUCTION.md) (the plan) and
[`deploy-toolforge.md`](deploy-toolforge.md) (first-time setup). Everything here
runs as the tool account on Toolforge (`become <toolname>`).

## Configuration (env vars)

Set with `toolforge envvars create <NAME> <value>`; the webservice and jobs see
them automatically.

| Variable                         | Required | Meaning                                                                                                                                                                                                                   |
| -------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TOOLHUB_DB_URL`                 | yes      | SQLAlchemy URL for ToolsDB, e.g. `mysql+pymysql://sXXXX:PW@tools.db.svc.wikimedia.cloud/sXXXX__toolhub_evolved`                                                                                                           |
| `TOOLHUB_SECRET_KEY`             | yes      | Stable random string (`python3 -c "import secrets;print(secrets.token_hex(32))"`) — signs session cookies. The app refuses to start without it unless `TOOLHUB_INSECURE_COOKIES=1` marks the process as local development |
| `TOOLHUB_OAUTH_CLIENT_ID`        | yes      | Official Toolhub OAuth application client id (see below)                                                                                                                                                                  |
| `TOOLHUB_OAUTH_CLIENT_SECRET`    | yes      | The Toolhub OAuth application's client secret                                                                                                                                                                             |
| `TOOLHUB_DB_NAME`                | yes      | ToolsDB database name for backups, e.g. `sXXXX__toolhub_evolved`                                                                                                                                                          |
| `TOOLHUB_EVOLVED_BASE_URL`       | no       | Canonical public base URL used to build the OAuth callback, e.g. `https://<toolname>.toolforge.org`                                                                                                                       |
| `TOOLHUB_EVOLVED_REVIEWER_USERS` | no       | Comma-separated Toolhub numeric ids or usernames promoted to the Evolved-only `reviewer` role on login                                                                                                                    |
| `TOOLHUB_EVOLVED_ADMIN_USERS`    | no       | Comma-separated Toolhub numeric ids or usernames promoted to the Evolved-only `admin` role on login                                                                                                                       |
| `TOOLHUB_API_BASE`               | no       | Toolhub base URL override for staging/tests; defaults to `https://toolhub.wikimedia.org`                                                                                                                                  |
| `TOOLHUB_BACKUP_DIR`             | no       | Backup destination (default `~/backups`)                                                                                                                                                                                  |
| `TOOLHUB_TOKEN_KEY`              | no       | Independent key for encrypting stored Toolhub OAuth grants; defaults to deriving one from `TOOLHUB_SECRET_KEY`                                                                                                            |
| `TOOLHUB_GITHUB_TOKEN`           | no       | Server-only token with permission to create issues in the configured Evolved repository; enables authenticated in-app issue reporting                                                                                     |
| `TOOLHUB_GITHUB_REPOSITORY`      | no       | GitHub `owner/repository` target for in-app issue reports (default `schiste/toolhub-evolved`)                                                                                                                             |
| `TOOLHUB_GITHUB_ISSUE_LABELS`    | no       | Optional comma-separated labels applied by the server to published reports                                                                                                                                                |
| `TOOLHUB_INSECURE_COOKIES`       | no       | Set to `1` only for local http development — never in production                                                                                                                                                          |

Without `TOOLHUB_DB_URL` the backend falls back to a repo-local SQLite file
(fine for development, unsafe on NFS under real traffic). Without the OAuth
vars, `/oauth/login` answers 503 and the site runs with live reads plus
signed-out read-only mode. Without a stored per-user Toolhub grant, `/v1/write/*`
write endpoints answer 401 with `reauth: true`.

Authenticated issue reporting is disabled unless `TOOLHUB_GITHUB_TOKEN` is set.
The token is never sent to the browser. A signed-in user must review and
explicitly approve the drawer contents before the CSRF-protected
`POST /v1/issue-reports/` endpoint publishes a public GitHub issue. The
endpoint accepts bounded route diagnostics only, and the `issue_reports` table
deduplicates retries by client report id.

## Stored Toolhub grants (encryption at rest)

`toolhub_tokens` holds official Toolhub bearer credentials, and on Toolforge it
lives in shared ToolsDB and in every backup this runbook takes. Rows are
therefore sealed with Fernet before they are written (`backend/token_crypto.py`).

- The key is derived from `TOOLHUB_SECRET_KEY` via HKDF, so no extra
  configuration is needed. Set `TOOLHUB_TOKEN_KEY` if you want to rotate the
  session key without invalidating stored grants.
- **Rotating the key forces re-authorization.** A grant that cannot be decrypted
  is deleted and the user is sent back through `/oauth/login`; nothing else
  breaks and no manual cleanup is needed.
- Every stored grant is sealed; the pre-encryption rows were migrated and the
  plaintext compatibility path has been removed. An unsealed value now fails
  closed like any other unreadable one. To confirm the invariant still holds:
  `SELECT COUNT(*) FROM toolhub_tokens WHERE access_token NOT LIKE 'v1:%'`
  should return 0.

## Evolved-local roles and permissions

Toolhub OAuth is the only sign-in path. A successful login calls official
Toolhub `GET /api/user/`, maps that identity into the local `users` table, and
stores the official OAuth grant server-side for `/v1/write/*` writes.

Evolved permissions are separate from Toolhub permissions:

- `user` — baseline role for every signed-in Toolhub user. Can manage their own
  private Evolved data: drafts, overlays, favorites cache/fallback, lists,
  crawler URLs, thanks, health targets, and submitted media.
- `reviewer` — Evolved-only reviewer/moderator role for public local queues
  such as local tool records, health targets, media, and flagged thanks. It
  does not grant private-data access to other users.
- `admin` — Evolved-only operator role for future local administration. It does
  not grant any special right on official Toolhub.

Role promotion can be bootstrapped with
`TOOLHUB_EVOLVED_REVIEWER_USERS` / `TOOLHUB_EVOLVED_ADMIN_USERS`. Values match
either the stable Toolhub numeric user id or the current username, case
insensitively. The persistent source is `users.role`; the env vars promote a
matching user during login so operators do not need to expose Toolhub OAuth
tokens or browser-side state.

Official writes are still governed by official Toolhub. An Evolved `admin` can
ask `/v1/write/*` to call Toolhub with their own stored OAuth grant, but Toolhub
remains the permission authority and may reject the request.

## Toolhub OAuth application (one-time)

1. Sign in to Toolhub and create an OAuth application from Toolhub's developer
   settings. Use OAuth **2.0**, authorization-code flow, confidential client,
   callback `https://<toolname>.toolforge.org/oauth/callback`, and scopes
   `read write`.
2. Store the client id/secret via `toolforge envvars create` (never in the
   repo). Set `TOOLHUB_EVOLVED_BASE_URL` if the public callback URL cannot be
   inferred reliably from Toolforge proxy headers.
3. Smoke-check the flow: `/oauth/login` should redirect to
   `https://toolhub.wikimedia.org/o/authorize/`, the callback should create a
   local user using `GET /api/user/`, and `/v1/config/` should report
   `"oauth": true` and `"officialWrites": true`.

For local browser testing without a Toolhub OAuth application, set
`TOOLHUB_INSECURE_COOKIES=1` and `TOOLHUB_DEV_LOGIN=1`, then visit
`/oauth/dev-login?next=/my-tools` on `localhost` or `127.0.0.1`. This creates an
Evolved-only session and deliberately does not store a Toolhub OAuth grant, so
`/v1/user/` reports `"officialWrites": false`.

## Database (ToolsDB)

- Create once: `sql tools` then `CREATE DATABASE sXXXX__toolhub_evolved;`
  (credentials come from `~/replica.my.cnf`).
- Schema: the app creates missing tables at startup (`Base.metadata.create_all`
  — idempotent, additive only). A column change needs a manual
  `ALTER TABLE` (write it down in the deploy notes) or a table rebuild; if
  migrations become frequent, introduce Alembic at that point.

## Evolved-Owned Backend Data

The feature plan in [`HYBRID-FEATURE-PLAN.md`](HYBRID-FEATURE-PLAN.md) is the
planning register for data and features that do not exist in official Toolhub.
Keep this runbook current whenever a local table, job, retention rule, or
failure mode changes.

Shared provenance vocabulary lives in `backend.sync`: `official`,
`local_draft`, `local_fallback`, `evolved_real`, and `sync_error`. Local tables
that can cache, publish, review, or repair Evolved data carry the relevant mix
of `source`, `sync_status`, `official_id`/`official_name`, `last_synced_at`,
`last_error`, `created_by_user_id`, `deleted_at`, and `review_status`.
`tool_media.source` remains the human-entered media attribution/source field;
its Evolved provenance is tracked through `sync_status`, review state, creator,
errors, and deletion state.

Canonical data rule: official Toolhub catalog data is never replaced by local
rows. Single-tool reads ask live Toolhub first and use a local new-tool record
only after an upstream `404`; server-side crawler ingestion skips names that
already exist upstream; local edit/annotation overlays strip canonical identity
fields such as `name` and `origin` before storage or merge.

Read-proxy cache rule: `api_cache` stores only anonymous official Toolhub
`GET /api/*` responses. It never stores `/v1/user`, OAuth/session responses,
CSRF-protected writes, or official write payloads made with a user's Toolhub
grant. Rows are performance artifacts with `fetched_at`, `expires_at`,
`stale_until`, validators (`etag`, `last_modified`), and `last_error`; they can
be safely truncated if stale or oversized.

Browser cache rule: the SPA may store a bounded localStorage cache under
`toolhub-api-cache:v1`, again only for anonymous `/api/*` reads. It exists solely
to make hard refreshes feel instant: stale public data is rendered first, the app
shows a refresh toast, and the route repaints after the freshest API response is
available. Clearing browser storage only removes this performance cache and does
not affect Evolved server data.

Anonymous API cache TTLs:

| Endpoint family                            | Fresh TTL | Stale-if-error window |
| ------------------------------------------ | --------- | --------------------- |
| `/api/recent/`                             | 30s       | 24h after freshness   |
| `/api/search/tools/`                       | 2min      | 24h after freshness   |
| `/api/tools/:name/`, `/api/lists/:id/`     | 15min     | 24h after freshness   |
| `/api/schema/` and controlled vocab/config | 24h       | 24h after freshness   |
| Other anonymous `/api/*` GETs              | 1min      | 24h after freshness   |

Shared cache invalidation and prewarming:

- User-facing proxied anonymous `GET /api/*` requests do not poll Toolhub recent
  changes. The scheduled `api-cache-invalidator` job runs every minute and owns
  the `GET /api/recent/?page_size=50` poll. `api_cache_meta` stores the last
  poll time and latest seen recent-row timestamp/id so all workers share the
  same invalidation state.
- On new recent rows with `content_type = tool`, Evolved invalidates cached
  `/api/tools/<name>/` reads, tool sub-resources such as revisions, `/api/recent/`,
  `/api/search/tools/`, and `/api/ui/home/`.
- On new recent rows with `content_type = list`, Evolved invalidates cached
  `/api/lists/<id>/`, `/api/lists/`, and `/api/recent/`.
- A successful official write through `/v1/write/*` or the compatibility
  `/v1/toolhub/*` bridge invalidates the affected shared cache paths immediately.
  Rejected writes that become local fallback records do not invalidate official
  Toolhub cache rows.
- After invalidation, the same job prewarms hot anonymous reads and derives
  recent-page owner labels into `tool_owner_cache`, so the first visitor after a
  scheduled run or deploy is not responsible for the cold cache fill.

Anonymous `/api/*` responses include cache diagnostics for operators and browser
debugging:

- `X-Toolhub-Evolved-Cache: hit|miss|stale|revalidated` describes whether the
  response came from the shared cache, live upstream, stale fallback, or a
  conditional 304 revalidation.
- `X-Toolhub-Evolved-Upstream` records the represented Toolhub result, such as
  `200`, `304`, `503`, or `timeout`. Cached hits report the cached upstream
  status; stale fallbacks report the failed revalidation result.
- `Server-Timing` carries machine-readable timings for browser DevTools:
  `cache;desc="hit|miss|stale|revalidated"`, `upstream;desc="<status>";dur=<ms>`
  when an upstream request was made, and `app;dur=<ms>` for total Flask request
  handling.

Frontend diagnostics are exposed in the browser Performance timeline and in
`globalThis.__toolhubEvolvedTimings` for quick console inspection. Current timing
names are:

- `toolhub-evolved:app-boot-start` and `toolhub-evolved:app-boot`
- `toolhub-evolved:labels-loaded`
- `toolhub-evolved:first-content-paint`
- `toolhub-evolved:first-api-response`
- `toolhub-evolved:stale-cache-served`
- `toolhub-evolved:fresh-refresh-completed`

| Data                                                               | Visibility                                             | Operational note                                                                                                                                                                                                                        |
| ------------------------------------------------------------------ | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `api_cache`                                                        | Anonymous public Toolhub API payload cache             | Shared worker cache for `GET /api/*`; not canonical data, safe to clear, stale rows may be served only during transient upstream failures.                                                                                              |
| `api_cache_meta`                                                   | Anonymous cache coordination state                     | Stores the recent-change poll throttle and latest timestamp/id marker; safe to clear, which causes the next poll to baseline without deleting cache rows.                                                                               |
| `canonical_tool_cache`                                             | Anonymous public canonical cache                       | Resumable mirror of official `/api/tools/` records used by local enrichment; rebuildable from Toolhub and never a replacement for live canonical reads.                                                                                 |
| `graph_tool_enrichment`                                            | Anonymous public derived graph facets                  | Versioned materialization of graph-relevant metadata with per-value provenance; rebuilt from canonical, crawler, discovered toolinfo, and approved repository sources.                                                                  |
| `catalog_tool_projection` / `catalog_facet_values`                 | Anonymous public Evolved catalog projection            | Versioned effective records, per-field evidence, validation state, and indexed facets; canonical Toolhub rows remain untouched and the scheduled repair job rebuilds missing versions.                                                  |
| `catalog_curations`                                                | Pending/private review; approved evidence public       | Reviewer-approved local corrections only. Proposals never mutate canonical Toolhub data and do not affect projections before approval.                                                                                                  |
| `tool_asset_cache`                                                 | Anonymous public derived icon metadata                 | Rebuildable index for size/type-checked icons stored under `$TOOLHUB_ASSET_CACHE_DIR`; web reads never fetch remote URLs and missing files fall back safely.                                                                            |
| `tool_catalog_sync_state`                                          | Operational cursor state                               | Stores the paginated catalog-sync cursor, pacing run status, completion cycles, and last error; safe to reset to page 1 to rebuild the mirror.                                                                                          |
| `toolhub_account_projection`                                       | Anonymous official account projection                  | Complete local projection of accounts registered with official Toolhub, keyed by immutable Toolhub user id; it is deliberately separate from Evolved-authorized `users`.                                                                |
| `toolhub_account_sync_state`                                       | Operational cursor state                               | Stores the account generation, next page, completed cycles, official count, and last error; partial generations never prune the last complete directory.                                                                                |
| `toolforge_account_projection` / `toolforge_membership_projection` | Anonymous official infrastructure projection           | Complete LDAP projection keyed by immutable developer `uidNumber`; stores Developer account `cn` and Unix shell `uid` separately, and retains all current `tools.*` service-group edges, including accounts not yet linked to a person. |
| `toolforge_account_sync_state`                                     | Operational cursor state                               | Generation and completion state for the Toolforge account projection; failed generations retain the last complete account and membership set.                                                                                           |
| `maintainer_backfill_state`                                        | Operational cursor state                               | Stores the paced Toolsadmin maintainer backfill cursor, cycle counters, and failures; safe to reset to restart the derived maintainer projection.                                                                                       |
| `tool_owner_cache`                                                 | Anonymous public derived owner cache                   | Owner-by-tool labels for `/recent`; derived from official Toolhub tool details, safe to clear, never canonical authorship or permission state.                                                                                          |
| `users`                                                            | Private account mapping                                | Local identity row derived from Toolhub OAuth and `GET /api/user/`; includes the Evolved-only `role`; delete with the user's Evolved account data.                                                                                      |
| `toolhub_tokens`                                                   | Secret                                                 | Server-side Toolhub OAuth grant; never expose through `/v1`; rotate/delete on reconnect, logout-all, or account deletion.                                                                                                               |
| `favorites`                                                        | Private per user                                       | Cache/fallback only; official Toolhub favorite state wins after successful sync; new rows record `created_by_user_id`.                                                                                                                  |
| `lists`                                                            | Private/user-visible fallback                          | Store local drafts or rejected official writes; keep official ids, creator, soft-delete, sync status, Toolhub response details, and validation errors.                                                                                  |
| `tools`                                                            | Local draft or public Evolved feed row                 | Never mirror official Toolhub tools; public local records require `review_status = approved` and feed `/toolinfo.json` for possible upstream ingestion.                                                                                 |
| `tool_overlays`                                                    | User-visible local delta                               | Field patches for edits/annotations rejected by Toolhub or kept as drafts; strip canonical identity fields and keep Toolhub validation metadata.                                                                                        |
| `activity`                                                         | User-visible/admin-visible depending on event          | Local audit/revision rows only; include local provenance and merge with live Toolhub feeds without pretending to be official Toolhub activity.                                                                                          |
| `crawler_urls`                                                     | Private until surfaced in local crawler UI/feed        | Local URL registrations and official-write fallbacks; scheduled jobs fetch only enabled local URLs; failed official writes keep validation details.                                                                                     |
| `crawler_runs`                                                     | Operational/user-visible history                       | Per-run crawler outcomes; useful for failure emails, user debugging, and restore checks.                                                                                                                                                |
| `toolinfo_discovery`                                               | Owner-facing Evolved cache                             | Per-tool automated root/sitemap `toolinfo.json` discovery state shown on My tools; seeded from official Toolhub listings and owner resolver candidates; not canonical.                                                                  |
| `toolinfo_discovery_meta`                                          | Operational cursor state                               | Stores the official `/api/tools/` page cursor used by the automated discovery job; safe to reset to page 1 by clearing the row.                                                                                                         |
| `toolinfo_sources`                                                 | Official crawler source evidence cache                 | Mirrors official `/api/crawler/urls/` registrations and fetch status; safe to rebuild, not a canonical copy of tool records.                                                                                                            |
| `toolinfo_source_items`                                            | Per-tool official feed source evidence                 | Maps tool names to the official crawler feed item that declared them; stores compact feed payload evidence for My tools and future provenance features.                                                                                 |
| `toolinfo_source_generations`                                      | Operational source audit history                       | Records every completely fetched feed document by content hash. Failed reads never create a deletion generation or replace the last good item projection.                                                                               |
| `toolinfo_source_attestations` / `toolinfo_author_bindings`        | Rebuildable identity evidence                          | Classifies feed control and binds each source-local author token only through stable handles, verified source control, or an independently verified same-source tool anchor. Conflicts fail closed.                                     |
| `tool_events`                                                      | Aggregate-only user-visible metrics                    | Signed-in Evolved interactions; use only for privacy-limited aggregates and delete per-user rows on data deletion.                                                                                                                      |
| `tool_thanks`                                                      | Public aggregate, private user relation                | One active thanks per user/tool; counts include only `review_status = approved`, are labeled as Evolved data, and are deleted with the user's local data.                                                                               |
| `tool_author_claims`                                               | Public provenance label, private evidence cache        | Per-tool verification claims owned by stable local `user_id`; `toolhub_username` is only a mutable display snapshot. Never treat a claim as official Toolhub permission state.                                                          |
| `toolinfo_control_challenges`                                      | Private, expiring verification workflow                | Short-lived challenges proving an account can change one exact external `toolinfo.json` URL; never a canonical Toolhub ownership or write grant.                                                                                        |
| `tool_author_keys`                                                 | Public-key registry for signed toolinfo claims         | Stores Evolved-registered public keys owned by stable local `user_id`; never store private keys, and ignore revoked keys during verification.                                                                                           |
| `people` / `person_identifiers`                                    | Public identity projection                             | People have immutable Evolved public ids. Toolhub and Wikimedia numeric ids are stable; Toolhub, Toolforge, and wiki usernames are mutable handles. Display-only rows are not people.                                                   |
| `person_account_bindings`                                          | Public identity proof, private audit metadata          | One provider account keyed by its immutable external id, bound only through an official stable bridge, authenticated control proof, or operator decision. Candidate and conflict rows never merge people.                               |
| `account_link_challenges`                                          | Private, expiring security state                       | Ten-minute, single-use, user-bound SSH-signature challenges. Challenge hashes and attempt state are stored; private keys and submitted signatures are not retained.                                                                     |
| `person_profiles`                                                  | Evolved-owned public profile                           | Bio, links, avatar, location, and visibility belong to Evolved. Toolhub remains canonical for catalog records and permissions.                                                                                                          |
| `tool_relationship_evidence`                                       | Provenance ledger                                      | Toolhub author/actor metadata, LDAP membership, Toolsadmin labels, and Evolved claims remain separate evidence. Toolsadmin labels alone stay unresolved; raw evidence payloads are private and no row grants Toolhub permissions.       |
| `unresolved_attribution_evidence`                                  | Public aggregated attribution, private evidence detail | Display-only labels retain tool, role, source, status, confidence, and freshness without receiving a person id. Current source refreshes withdraw obsolete observations.                                                                |
| `person_tool_relationships`                                        | Public typed relationship projection                   | One resolved current row per tool, person, and role; many evidence rows can support it. `catalog_actor` is never promoted to `record_owner` without explicit write-access evidence.                                                     |
| `person_activity_summaries`                                        | Public contribution read model                         | Rebuildable, person-keyed summary of approved/public contributions only; registration and private account actions do not imply active maintenance.                                                                                      |
| `person_reconciliation_runs`                                       | Operational audit                                      | One dry-run or apply pass with deterministic counts, completion status, and error state.                                                                                                                                                |
| `person_reconciliation_mappings`                                   | Operational review                                     | Durable candidate, approved, rejected, or split source/target mappings with bounded evidence, confidence, reviewer, and notes. Approved mappings are reapplied after source refreshes.                                                  |
| `person_reconciliation_conflicts`                                  | Operational review                                     | Stable-identifier and provider-binding contradictions deliberately left unresolved; never used as automatic merge evidence.                                                                                                             |
| `person_reconciliation_queue`                                      | Operational work queue                                 | Deduplicated changed-tool names waiting for bounded incremental edge and relationship reconciliation, with retry state.                                                                                                                 |
| `source_analysis_reports`                                          | Private per user                                       | Stores derived, redacted source-analysis findings and maintainer review state; raw source files are never stored and rows are included in export/delete operations.                                                                     |
| `tool_health_targets` / `tool_health_checks`                       | Public checked status after approval                   | Maintainer/user-provided targets stay hidden until `review_status = approved`; scheduled checks must use conservative timeouts and store errors without faking health.                                                                  |
| `tool_media`                                                       | Public only after approval                             | URL-based screenshots/media with license and source; pending rows are hidden until reviewed, labeled as Evolved data, and can be soft-deleted.                                                                                          |

`tool_author_claims` is the account-owned relationship workflow, not a second
relationship projection. Rows are scoped to one `(tool_name, author_name,
account, verification_method)` tuple and record the method-derived requested
role. `verification_status` is one of `verified`, `unverified`, `stale`,
`failed`, or `revoked`; `verification_method` is one of
`toolforge_maintainer`, `toolhub_write_access`, `signed_toolinfo`,
`toolinfo_url_control`, or
`author_display_name`. `author_display_name` is explicitly non-verified
display metadata unless another method verifies the same per-tool claim.
Verification is never global to an author display name or Toolhub username:
`Christophe` verified on `toolhub-evolved` does not verify `Christophe` on any
other tool without a separate verified claim row for that exact tool.
`GET /v1/me/tools/` performs no upstream author search and invents no aliases.
It reads the same canonical `person_tool_relationships` graph as public People
profiles, joins compact local Toolhub records, and returns every role on each
tool. The six-hourly Toolforge projection preserves all developer memberships;
verified `person_account_bindings` turn those memberships into per-tool
maintainer evidence. This makes a signed-in user's workbench and public profile
converge on one relationship contract instead of maintaining two resolvers.
Successful official
Toolhub tool writes add `toolhub_write_access` claims without affecting the
write response if evidence recording fails. Crawler ingestion records
`signed_toolinfo` claims before upstream-name de-dupe, so official Toolhub data
remains canonical while Evolved can still retain signed authorship evidence.
The user-facing workflow is exposed through
`GET /v1/tools/<name>/claim-options/`, `POST /v1/tools/<name>/claims/`,
`GET /v1/me/claims/`, `POST /v1/claims/<id>/verify/`, and
`DELETE /v1/claims/<id>/`. Revocation retains the workflow and immutable
evidence history, marks its evidence withdrawn, and removes the derived current
relationship. Toolhub write authority is never self-asserted: it is recorded
only after a successful official tool write.

Submitting a crawler URL or a create-time `toolinfo_url` is not an ownership
proof. The My tools workspace can create a short-lived URL-control challenge
through `POST /v1/toolinfo/ownership-challenges/`. The user publishes the
returned token at `x_toolhub_evolved_verification.challenge` in the exact
toolinfo document, then calls the matching verify endpoint. Evolved refetches
the exact HTTPS URL through the strict public-fetch policy, checks the tool name
and token, and only then creates a per-tool `toolinfo_url_control` maintainer
claim. The challenge expires after 24 hours; the resulting claim expires after
30 days. This proves control of that metadata endpoint, not control of the
official Toolhub record, a repository, or a Toolforge account.

The `maintainer-backfill` job is a catalog-wide attribution audit. It walks
the local canonical cache, infers exact Toolforge account names from
`toolforge-<name>` records and Toolforge URLs, fetches each public Toolsadmin
maintainer page at a minimum three-second interval, and stores rebuildable
`toolforge_toolsadmin` observations. Page labels remain unresolved attribution;
they become verified relationships only when a unique projected Developer
account has the exact LDAP project membership and an independently verified
person binding. A successful empty page withdraws old observations for that
account, while a transient HTTP or network failure keeps the last known evidence
and retries on the next cycle. The job processes 60
tools per hour by default, checkpoints after every tool, and completes a
several-thousand-tool backfill over repeated cycles without running inside web
requests.

The normalized people view is available from `GET /v1/people/tools/<name>/`.
Person-centric reads use `GET /v1/people/<person_slug_or_public_id>/` and
`GET /v1/people/`. New links use the immutable `slug` and `canonicalPath`
returned by person projections; UUID paths remain permanent compatibility
inputs and the frontend replaces them with the canonical readable path.
Legacy `/by/<name>` routes call
`GET /v1/people/resolve/?handle=<name>`. The resolver returns `resolved` only
when one public person owns the exact current Toolhub, Toolforge, or wiki
handle. Cross-namespace handle collisions, public display-name matches, and
matching unresolved attribution labels return `ambiguous`; display names never
select a person. The frontend renders those candidates and unresolved evidence
as a disambiguation page. `not_found` alone may use the canonical Toolhub author
aggregate fallback while local projections catch up.
The directory and person-detail route publish only identities backed by a
current stable identifier, a current handle, or an Evolved profile. Display-only
evidence remains scoped per observation and is returned separately as aggregated
`unresolvedAttributions`; those entries deliberately have no person id or profile
URL. One
person may have two public relationships to the same tool: `author` means the
canonical Toolhub author field listed the person, while `maintainer` means
Evolved has operational evidence such as Toolforge membership or signed
toolinfo. The graph also retains `record_owner` for authorization and
`catalog_actor` for contribution eligibility and auditing, but those internal
signals are not returned as public person–tool relationships, filters, counts,
or badges. Toolhub's immutable numeric user id and
the Wikimedia CentralAuth global user id are stable account links. Toolhub,
Toolforge developer, and wiki usernames are case-insensitive mutable handles.
Display-name observations are aggregated for discovery but do not receive a
public person id.

External account binding does not require a person to authorize Evolved.
Official Toolhub user ids bind Toolhub accounts; Toolhub and Toolforge both
expose Wikimedia global ids that bridge accounts automatically; and Toolforge
`uidNumber` identifies developer accounts across renames. Several Toolforge
developer accounts may bind to one person when each carries the same official
Wikimedia global id. One immutable provider id resolving to different people is
a conflict and is copied into the operator review queue.

Signed-in users can repair legacy accounts that lack the Wikimedia bridge via
`GET /v1/me/account-links/`,
`POST /v1/me/account-links/toolforge/challenges/`, and
`POST /v1/me/account-links/toolforge/verify/`. Evolved issues a ten-minute
challenge bound to the local user, person, and immutable Toolforge `uidNumber`.
The user signs it locally with OpenSSH SSHSIG; Evolved verifies the signature
against the account's current public `sshPublicKey` values read directly from
LDAP. The private key never leaves the user's machine. A successful proof binds
all current memberships for that developer account, and later syncs include new
memberships automatically. Each additional legacy developer account is proven
separately. The proof establishes account control and identity only: it grants
neither Toolhub write access nor a global owner role.

The Community directory presents one search contract over three evidence classes:

- A **person** result is a public identity backed by stable evidence and
  connected to a tool relationship or public profile. An official account is
  folded into this result only through immutable Toolhub or Wikimedia ids.
- An **account-only** result is registered with official Toolhub but has no
  safely linked public person or tool relationship. Registration alone does
  not demonstrate catalog contribution.
- An **unresolved attribution** is a display label observed in tool metadata.
  It remains searchable but never receives a public person id merely because
  its text resembles a person or account name.

`GET /v1/community/` is the product-facing composition endpoint. It searches
person names and handles, official Toolhub usernames, catalog tools, and
unresolved labels without pretending those evidence classes have equal trust.
The response separates `primaryResults` (people and account-only matches),
`relatedTools` (relationship-backed or strong structured-field matches),
`unresolvedEvidence` (standalone display-label clusters), and `otherMatches`
(description-only mentions). The legacy `results` key aliases `primaryResults`
for compatibility. An exact display label is folded into a stable person's
`supportingEvidence` only when exactly one stable person has that exact label;
the evidence is not merged into the identity. Each related tool appears once
and carries every applicable typed relationship with its status and provenance.
A tool-text match returns the tool card itself; it does not fan out into every related person. It supports relationship,
verification, activity, project, contributor, ordering, and pagination
parameters. `contributor=observed` filters rather than switching directories;
eligible people include their canonical catalog-actor or approved public
activity basis. Result badges remain scoped: account identity evidence does not
verify a tool relationship, and a verified relationship does not certify every
aspect of a person's identity.

`GET /v1/accounts/` reads only the complete local account projection and
supports `q`, `group`, `ordering=name|recent`, `page`, and `page_size`. Its
`count` covers the filtered projection, and its `sync` object distinguishes a
ready directory, a usable stale generation, an in-progress first build, and an
unavailable projection. `GET /v1/accounts/<toolhub_user_id>/` returns account
registration facts. An account includes `personId` only when its immutable
Toolhub user id or Wikimedia CentralAuth global user id identifies exactly one
public person. Usernames are never an automatic cross-link.

The `account-sync` job walks official `/api/users/` pages ordered by immutable
`id`, upserts every page under a generation, and checkpoints its next page.
Only a final page whose distinct generation rows equal Toolhub's reported total
may remove records absent from the new generation. Network failures,
interruptions, count mismatches, and lock contention preserve the last complete
generation. Deployments run `account_sync.py --complete` before restarting, and
the six-hour Toolforge job repeats that complete, resumable refresh.

Historical reconciliation is deterministic and rerunnable. Run
`python proxy/people_reconcile.py` for a database-backed dry-run, inspect the
recorded mappings and conflicts, then run it with `--apply` to materialize
canonical Toolhub metadata evidence and rebuild all typed relationships. The
official account sync materializes stable public people from immutable Toolhub
user ids and Wikimedia global user ids; OAuth remains a separate consent and
write-authority concern.

Apply runs hydrate every complete Toolhub and Toolforge projection by immutable
ids. Wikimedia global ids bridge provider accounts automatically. Exact
cross-provider handles without that bridge remain candidates and never merge
people; display-only evidence remains in `unresolved_attribution_evidence` and
is not considered an identity candidate. Roles are preserved: Toolhub author
evidence remains authorship, while a verified LDAP membership proves current
Toolforge maintenance. Neither path grants Toolhub write authority.

LDAP memberships are projected onto canonical Toolhub records through a
case-insensitive Toolforge project alias index. The conventional
`toolforge-<project>` catalog name, a `<project>.toolforge.org` deployment URL,
or a Toolsadmin `/tools/id/<project>` API URL can establish that alias. This
also covers older canonical names such as `mix-n-match` and duplicate Toolhub
records pointing to the same deployment. When no canonical alias exists, the
relationship remains available under the conventional fallback key; a later
catalog sync moves it to every proven canonical record and withdraws the old
fallback evidence. Titles and display-name similarity are never alias proof.

Deployments run `proxy/public_identity_smoke.py` inside a Toolforge webservice
environment before identity reconciliation. The probe requires a readable
`posixAccount` carrying `wikimediaGlobalAccountId`; failure aborts the deploy
before the serving process is restarted.

Admins use `GET /v1/moderation/people-conflicts/` to inspect pending identity
ambiguities and `PUT /v1/moderation/people-conflicts/<id>/` to mark one pending,
resolved, or dismissed with review notes. They use
`GET /v1/moderation/people-candidates/` to inspect exact public-account candidates and
`PUT /v1/moderation/people-candidates/<id>/` with `decision` set to `approved`,
`rejected`, or `split`. Approval moves the original provenance to the stable
person without changing its relationship role; rejection and split decisions
move nothing. Every decision is durable and none grants Toolhub permissions.

After deployment, run a dry pass first and inspect its summary, then run the
bounded apply pass:

```sh
.venv/bin/python proxy/people_reconcile.py
.venv/bin/python proxy/people_reconcile.py --apply --candidate-label-limit 25
.venv/bin/python proxy/people_reconcile.py --identities-only --candidate-label-limit 100
```

The apply pass backfills OAuth account links, rebuilds canonical and claim
evidence, reapplies approved or evidence-backed automatic mappings, refreshes
activity summaries, and queues new exact-name candidates. `--identities-only`
skips the expensive catalog-wide tool rebuild and is used by the hourly
`people-identity-reconcile` job; candidate cooldown ensures each run advances
through the population while retrying transient failures later. A non-zero
`stableIdentityConflicts` count requires operator review; the reconciler never
chooses between disagreeing stable ids.

Canonical Toolhub fetches and local Toolinfo ingestion enqueue affected tool
names in `person_reconciliation_queue` after their write transaction commits.
The `people-reconcile-incremental` job drains up to 100 queued tools each
minute, refreshing only those tools' metadata and claim edges. This keeps the
request path asynchronous while making new or changed data visible to the
people index promptly. The six-hour historical job remains necessary because
cross-tool stable-identifier merges and old conflicts require a global scan.

Signed toolinfo metadata is read from `x_toolhub_evolved_signature` or
`x-toolhub-evolved-signature`. The signed bytes are the canonical JSON toolinfo
item with that metadata removed. Active `tool_author_keys` rows are matched by
stable account id, key id, and algorithm; revoked keys are ignored. Operationally,
claims are time-bounded and may become `stale`, while public keys can be kept
until the user revokes them or deletes their Evolved-local data.

Developer settings exposes the public-key lifecycle for signed toolinfo:
`GET|POST /v1/author-keys/` lists/registers Ed25519 public keys,
`DELETE /v1/author-keys/<key_id>/` revokes one key, and
`POST /v1/toolinfo/signing-payload/` returns the canonical JSON and placeholder
signature metadata for the exact toolinfo object a maintainer wants to publish.
Evolved never stores or receives private keys.

Source analysis is an owner-facing maintainer aid, not a permission oracle.
`POST /v1/source-analysis/` accepts bounded text source files plus optional
repository context JSON, analyzes them without executing code, and stores only
the report: projects, APIs, access rights, external dependencies, lockfile
evidence, OAuth scopes, technology, repository context, deterministic
assessment scores, warnings, and evidence excerpts. Evidence is line-limited and
credential-looking assignments are redacted. `GET /v1/source-analysis/` and
`GET /v1/source-analysis/<id>/` are private reads for the report owner;
`POST /v1/source-analysis/<id>/review/` lets the owner mark a report `open`,
`approved`, or `rejected`. The same analyzer is available for local checkouts
through `PYTHONPATH=proxy python proxy/analyze_source.py`; the CLI can add local
Git metadata without network access.

Before adding a new Evolved-only table, document the owner, purpose,
visibility, retention/deletion behavior, export behavior, Toolhub handoff path,
abuse controls, and backup/restore impact in the feature plan and this runbook.

## Frontend provenance contract

Hybrid write surfaces must use the shared `sync-status` UI components rather
than ad hoc badges. Field groups that can show official data plus local overlays
must render field-level provenance labels. Supported user-visible states are
`Published to Toolhub`, `Saved locally`,
`Saved locally after Toolhub rejected it`, `Pending review`, and
`Retry available`.

Retry buttons must call the dedicated `/v1/write/*/retry/` fallback endpoints.
Discard buttons must call the matching fallback delete endpoint where the
backend stores one. Evolved-only public rows must be labeled as `Evolved data`
and use review badges rather than implying Toolhub approval.

## Public-data moderation

Reviewers/admins use `GET /v1/moderation/public-data/` to list pending
Evolved-only public data and
`PUT /v1/moderation/public-data/<kind>/<id>/` with `reviewStatus` set to
`pending`, `approved`, or `rejected` to change visibility. Supported kinds are
`tool-records`, `health-targets`, `media`, and `thanks`.

Approval only affects Toolhub Evolved. It can make a local tool record visible
in Evolved search and `/toolinfo.json`, or make local health/media/thanks data
visible on Evolved pages, but it never turns the row into official Toolhub data
and never grants Toolhub admin rights. All public write routes still require
Toolhub sign-in, CSRF, per-user rate limiting, and `backend.authz.can(...)`.

## GitHub issue hygiene

The hybrid foundation is tracked by parent epic #102. Keep feature-area child
issues linked from that epic and include a `Parent epic: #102` back link in each
child issue. Current children are identity (#103), UI provenance (#104),
official-first writes (#105), provenance (#106), docs hygiene (#107),
production cleanliness (#108), and Evolved-only public data controls (#109).

Before broad implementation or after changing the product model, search open
issues for removed demonstrator language:

```sh
gh issue list --state open --limit 200 \
  --json number,title,body \
  --jq '.[] | select(((.title // "") + "\n" + (.body // "") | test("experimental[ -]toggle|localStorage[ -]demo"; "i"))) | [.number, .title] | @tsv'
```

Refresh stale issue text to the production vocabulary:

- "Toolhub-first write" for official API attempts through `/v1/write/*`.
- "Evolved-local backend overlay", "draft", or "fallback" for local records.
- "Evolved data" for public data that official Toolhub does not expose.
- "Hybrid/Evolved roadmap" for prospective work, not a removed toggle.

Also keep labels aligned. The `lane-b` label describes prospective hybrid
Evolved roadmap work; it must not refer to the removed experimental-toggle
surface.

## Deploy / rollback

```sh
become <toolname>
sh ~/repo/tools/deploy.sh          # pull → stage release → build → restart → smoke-check → promote history
```

Rollback = `git -C ~/repo revert <sha>` (or `git reset --hard <good-sha>`)
followed by `sh ~/repo/tools/deploy.sh` again. The deploy script fails loudly
if the webservice doesn't come back healthy.

The release path deliberately serves the last successfully published account,
catalog, and identity projections. After smoke and manifest promotion, the
deploy queues `projection-refresh`, which refreshes Toolhub accounts, Toolforge
LDAP accounts, and the complete catalog concurrently when their last complete
generation is stale. Only after all required inputs succeed does one people
reconciliation publish the derived identity/source graph. A failed refresh
therefore leaves the prior public graph serving and is retried by the six-hour
schedule; it does not roll back otherwise healthy application code.

Each deploy stage appends structured JSON to
`~/deployment-diagnostics.jsonl`, including commit, timestamps, duration,
status, parsed row/cache metrics, and the failure phase. A non-zero
`webservice restart` result is provisional: the deploy still runs the bounded
HTTP readiness checks and records `recovered` when the replacement service is
actually healthy.

Every deploy stages a bounded 50-release manifest in `dist/data/deployments.json`,
then promotes that exact manifest to durable history only after the restarted
webservice passes its smoke check. The history is retained outside the checkout
so a `git pull --ff-only` remains clean. The What's New panel shows the latest two
curated releases; the Changelog page uses the retained history. A stable
`Release id` in both reviewed note files defines the public release: repeated
deployments with that ID update its serving commit without creating another
visible version. Change the ID and title only when intentionally starting a new
product release. The deploy is the publication point because it is the first
place that knows which commit actually reached production.

To rebuild the human-readable repository history locally, run
`npm run changelog:generate`. It groups conventional commits by date and change
type, and links every entry to its exact GitHub commit.

`npm run changelog:marketing` asks the local Chau7 raw MCP bridge to spawn one
release-note subagent from the pending Git range. It writes
`docs/CHANGELOG-TECHNICAL-MARKETING.md` for maintainers and
`docs/CHANGELOG-USER.md` for plain-language user announcements. The exact
`CHANGELOG.md` remains the source record. The pre-push hook generates these two
files into temporary paths and rejects a push when the checked-in versions are
missing or stale, so the generated copy must be reviewed and committed
explicitly.

To opt into the local Chau7 bridge, set
`TOOLHUB_CHAU7_MCP_BRIDGE=$HOME/.chau7/bin/chau7-mcp-bridge` before running the
hook or `npm run changelog:marketing`. A different raw MCP/API adapter can be
selected with `TOOLHUB_CHANGELOG_LLM_COMMAND`; it must read the prompt from stdin and write the constrained
`<TECHNICAL>...</TECHNICAL>` and `<USER>...</USER>` response to stdout. Set
`TOOLHUB_CHANGELOG_LLM_REQUIRED=1` in CI or a local shell when the provider
must be present.

## Scheduled jobs

Every scheduled entrypoint goes through `backend.job_runner.run_job()`, which
configures the database from `TOOLHUB_DB_URL`, optionally takes the shared
`toolhub-evolved:<job>` advisory lock, prints one summary format, and returns
the exit code defined in `backend.job_contract`. A job that loses the lock
prints `{"locked": true}` and exits zero, because losing a race with the run
already doing the work is a successful no-op. Three jobs whose flow genuinely
differs call `job_runner.configure()` and keep their own summary and exit code.

**Lock reclamation is derived, not guessed.** A pod killed at its timeout cannot
run the trap that releases its guard lock, so every guarded job sets
`--stale-after` to twice its own timeout: past that, no live run can still hold
the lock. A value at or below the timeout is worse than none, since it would
reclaim a lock from a run still working. Jobs declaring no timeout keep the
one-hour default. A test asserts the doubling for every job in `jobs.yaml`, so
a job added later cannot quietly inherit a wrong threshold.

**Exit codes are instructions, not reports.** `tools/job_guard.sh` counts
consecutive non-zero exits and trips a breaker, so a job exits non-zero only
when the sweep itself could not run or complete. Per-item failures — an
unreachable feed, an icon that would not fetch — are durable observations and
must not fail the run: `crawl.py` did exactly that, and one flaky URL retired
the crawler for ten days. Deviations are allowed but must state their reason
at the `return`.

**Public-registry lookups.** The hourly `people-identity-reconcile` job resolves
up to `PEOPLE_REGISTRY_LABEL_LIMIT` handle-shaped unresolved labels per run
against CentralAuth, four a second and serialized, walking a persisted cursor so
every label gets a turn and one the registry does not know is retried at most
once per sweep. The fetcher sends `maxlag` and obeys a `Retry-After` header, so
meta.wikimedia.org sets the ceiling rather than a delay guessed on its behalf; a
rate-limited lookup resolves nothing rather than inventing an identity. It targets attribution labels, which carry no person id — not the
display-name people the Toolhub candidate pass walks; aiming at the latter
checked nine labels while nine hundred sat untouched.

`backend.people_policy.is_handle_shaped` decides which labels are asked about:
self-chosen handles are admitted, multi-word purely alphabetic labels are
refused, because there a username and a person's name are indistinguishable and
a wrong bind misattributes a real individual. A label already matching a
publishable person's handle is skipped as resolvable locally. Set the limit to
`0` to disable the path.

A confirmed account becomes a person keyed on its immutable CentralAuth global
user id — the same class of identifier the account syncs already mint people
from, so it records a real account rather than inventing one. That is all it
does: the new handle makes the label resolvable by the ordinary
corroborated-handle rule the moment independent verified evidence ties that
person to a tool. The lookup publishes no relationship, and a person holding
none is not listed in the public directory, so a mistaken lookup stays
invisible. Handle provenance is `wikimedia_centralauth`, deliberately not a
trusted handle source. Run summaries report `registryChecked`,
`registryResolved`, and `registryPeopleCreated`.

**Duplication gates.** JavaScript is held at a strict zero
(`.jscpd.json`). Python runs against a ratchet in `.jscpd.python.json`,
currently **1%** against a measured 0.98% across 94 files. That gate had never
run at all — the original config listed only `format: ["javascript"]`, so the
whole Python job and backend layer was invisible to it, which is how the
entrypoint duplication accumulated unseen. The number may be **lowered, never
raised**; lower it in the same commit that removes the clones.

```sh
toolforge jobs load ~/repo/jobs.yaml       # crawler + source/discovery indexers + cache + backup
toolforge jobs list                        # status
toolforge jobs logs crawler                # last local crawl output
toolforge jobs logs toolinfo-discovery     # last root/sitemap discovery output
toolforge jobs logs toolinfo-source-index  # last official crawler source index output
toolforge jobs logs projection-refresh
toolforge jobs logs source-attestations
toolforge jobs logs api-cache-invalidator
toolforge jobs logs maintainer-backfill
toolforge jobs logs digest-publish
toolforge jobs logs digest-deliver
toolforge jobs logs digest-audit
```

Jobs are configured with Toolforge file logs. If the central `jobs logs`
endpoint has no retained stream, inspect the paths shown by
`toolforge jobs list -o long`, usually `~/catalog-sync.out` and
`~/catalog-sync.err`, without treating old appended errors as a current run.

Every scheduled job is wrapped by `tools/job_guard.sh`. A non-zero child exit
increments that job's consecutive-failure streak; the third consecutive failure
disables the child on subsequent schedules while preserving the failure email.
A successful run resets the streak.

The guard also holds a per-job lock, so a run that is still going when the next
one is due causes the newcomer to skip rather than overlap — routine for the
minute-scheduled jobs. Deliberate non-runs (a skipped overlap, `--reset`, an
already-disabled job) report on **stdout** and exit zero, so `<job>.err` carries
only real failures and is the file to read first.

The guard state is stored in `~/.toolhub-job-guard/` on the tool account's
shared home, and an operator can resume one job explicitly after fixing the
cause:

```sh
sh ~/repo/tools/job_guard.sh --job-name catalog-sync --reset
```

The reset only clears the guard; it does not run the job immediately. Use
`toolforge jobs run` for a controlled manual run.

The crawler exits non-zero (→ failure email) when any URL errored; per-run
results are also stored in the `crawler_runs` table. A name that already exists
upstream on Toolhub is a successful no-op, recorded in that table's `skipped`
column rather than `errors`, so a feed of entirely-canonical tools keeps
reporting green instead of walking the guard into a disable.

Every Python job calls `db.init_schema()` before doing work. Existing Toolforge
databases receive idempotent additive repairs there, including the catalog
reconciliation cursor columns and null retry-counter normalization. No database
reset is required after a deploy.

The Toolhub Digest's UTC period contract, Meta page layout, Lift Wing and
Wikimedia variables, delivery behavior, and recovery procedure are documented
in [DIGESTS.md](DIGESTS.md). Its publisher runs at 06:15 UTC and catches up all
missing closed non-empty periods; it never creates an empty edition.

`projection-refresh` is the six-hour projection coordinator. It reuses input
generations completed within six hours, runs stale Toolhub and Toolforge inputs
plus the incremental catalog path concurrently, then performs one
account/identity graph pass and computes `/v1/statistics/` ahead of user
traffic. It never initiates a complete catalog download. Toolinfo source reconciliation is content-hash
incremental; a changed reconciliation rules version forces one full pass, and
`source-attestations-full` provides an additional weekly full-audit backstop.
The full-source jobs have a 900-second timeout while the normal incremental
path should ordinarily be a fast no-op.

The crawler reads every enabled `crawler_urls` row hourly. For each toolinfo item
it first records valid `signed_toolinfo` author-claim evidence when the URL
owner has a matching active public key, then checks whether the tool name already
exists in official Toolhub. Official names are skipped so live Toolhub remains
canonical; Evolved-local rows are upserted only for names that Toolhub returns as
missing.

The API cache invalidator/prewarmer runs every minute. It polls official Toolhub
`/api/recent/?page_size=50`, records the latest seen marker in `api_cache_meta`,
deletes affected shared anonymous `/api/*` cache rows from `api_cache`, then
prewarms hot anonymous reads: `/api/ui/home/`, recent changes, schema, list
collections, and common `/api/search/tools/` queries. User-facing `/api/*`
requests must not poll recent changes themselves; they serve fresh/stale cache
immediately and refresh stale entries in the background.

The same pass reads the warmed `/api/recent/?page_size=30` payload and resolves
the visible tool owners into `tool_owner_cache`. `/recent` renders the recent
rows from `/api/recent/` first, then calls `GET /v1/recent/owners/` in bulk to
fill owner cells after the table is visible. The browser must not issue a burst
of `/api/tools/<name>/` detail requests for owner enrichment.

Common prewarmed search terms default to `wikidata,commons,toolforge,template,bot`.
Override them with `TOOLHUB_CACHE_PREWARM_SEARCH_QUERIES` as a comma-separated
Toolforge envvar when production traffic shows different common queries.

Tool creation can add `crawler_urls` rows too. When a signed-in user submits a
tool with the optional create-only `toolinfo_url` field, `/v1/write/tools/`
fetches that URL once with the same HTTPS/SSRF/size rules as the scheduled
crawler, fills missing optional create fields before the official Toolhub POST,
and stores the URL locally for future scheduled refreshes. A failed create-time
fetch does not block an otherwise valid official Toolhub create; it records a
`sync_error` row so the scheduler and crawler history can surface or retry it.

The Add/remove tools form may receive a homepage instead of a direct
`toolinfo.json` URL. `/v1/crawler/toolinfo-discovery/` checks the origin root
`/toolinfo.json` first. Only when that returns `404` does it fetch the origin
`/sitemap.xml`, scan same-origin HTTPS `<loc>` entries ending in
`toolinfo.json`, and test those candidates. A discovery miss is visible in the
URL list as `toolinfo.json not found` and does not create a `crawler_urls` row;
successful discovery continues through the normal official-first crawler URL
write path.

Automated owner-tool discovery is separate from crawler URL registration.
`/v1/me/tools/` ensures owner-visible Toolhub tools have a discovery row, including
`no_url` when the official record has no homepage to probe. The
`toolinfo-discovery` job also walks official `/api/tools/` pages using the
`toolinfo_discovery_meta` cursor, seeds discovery rows for all Toolhub tools it
sees, and refreshes up to 500 stale or pending rows every six hours with the
same root-first, sitemap-after-404 policy. My tools shows `found`, `not_found`,
`pending`, `error`, or `no_url` state to the owner. A `found` row is information
and provenance only; official Toolhub crawler registration still happens through
the existing signed-in write path.

Official crawler source indexing is the stronger automated provenance signal.
The `toolinfo-source-index` job mirrors public official `/api/crawler/urls/`,
fetches each registered JSON feed, validates items with the same minimum
Toolhub crawler fields (`name`, `title`, `description`, `url`), and writes
`toolinfo_sources` plus `toolinfo_source_items`. My tools uses that index to
show whether a tool came from Toolsadmin, a user-script aggregate, a wiki raw
feed, GitHub raw JSON, a self-hosted `toolinfo.json`, or another official
crawler feed. Root/sitemap discovery remains a secondary signal about whether a
tool's own homepage also exposes metadata. Unlike user-submitted local crawler
URLs, the source indexer allows public `*.toolforge.org`, `*.wmcloud.org`, and
`*.wmflabs.org` ingress hosts even when they resolve to internal service IPs
from Toolforge, and it follows redirects only after validating each hop.
Arbitrary private hosts are still refused.

Source identity reconciliation runs after every successful source-index batch
and as a six-hour local repair pass. A Toolforge-hosted feed is classified from
the complete LDAP membership projection: a single member is usable only when
its immutable account is already bound to a stable person; a multi-member
project remains group-controlled. Wikimedia user-page sources and explicit
URL-control challenges provide equivalent source-scoped proofs. Toolhub's
`created_by` value proves who registered a crawler URL, not who controls it.

Legacy developer accounts without a Toolforge↔SUL bridge remain candidates on
an exact Toolhub/Toolforge handle match alone. They are promoted automatically
only when current LDAP membership and an independent verified relationship
source corroborate that exact handle on the same canonical tool. The resulting
binding stores the immutable Toolforge UID number and the shared tool names;
conflicting stable identifiers still block publication.

Each toolinfo author becomes an independent assertion. The current schema's
author array and structured `wiki_username` / `developer_username` fields are
preferred. Legacy scalar values such as `Ada, Grace` are split for compatibility
but retain their raw value and a `legacyDelimited` audit flag; splitting alone
never verifies either identity. Once a source-local token is bound through a
verified controller or one independently verified tool edge, the same token can
produce author evidence for the source's other current canonical tools. A
target tool's Toolforge URL is evaluated separately against current LDAP
membership, so feed publication never implies operational maintenance.

Complete successful feed reads create generation rows and may withdraw missing
items and their derived evidence. Timeouts, invalid responses, and other failed
reads mark the source errored while preserving the last complete item and
relationship projection. Identity disagreements create
`toolinfo_source_identity` entries in the normal reconciliation conflict queue.

The `catalog-sync` job is the complete official catalog mirror. During the
initial backfill it walks `/api/tools/` with a resumable page cursor and upserts
each official record into `canonical_tool_cache`, so repository analysis and
local derived summaries do not depend on which catalog pages users happened to
visit. It runs every 15 minutes, fetches at most five pages of 100 records, and
waits at least three seconds between requests. A failed page is retried from
the same cursor on the next run rather than advancing past it.

After the first complete catalog cycle, the job stops repeated full ingestion.
Each run checks the newest `/api/recent/` page, fetches changed tool details
individually, and keeps failed detail names in a retry queue. It also reconciles
one `/api/tools/` page every 12 hours. It additionally hydrates at most ten
not-yet-detailed graph candidates per run, using a persistent name cursor and
the same three-second request spacing. This remains outside web requests and
within the Toolforge job's 300-second limit. The reconciliation spreads a full
safety pass over roughly a month for a catalog of several thousand tools while
keeping normal incremental traffic small. The `tool_catalog_sync_state` row
records the backfill and reconciliation cursors, recent marker, retry queue,
completed cycles, success/error state, and timestamps.

`catalog-integrity` is the separate twice-monthly backstop. It builds a new
complete generation, checks that the upstream count stayed stable throughout
pagination, and publishes it atomically; a moving catalog fails that candidate
generation without disturbing the last complete mirror. Ordinary deploys and
projection refreshes do not invoke this full-snapshot path.

The public graph endpoint never fetches Toolhub synchronously. It derives a
bounded nearest-neighbor graph from this shared canonical cache, reports facet
coverage, and preserves multi-value memberships. Its derived taxonomy splits
comma-delimited technology values and separates known hosting/runtime platforms
(including Toolforge) into the `platform` facet without rewriting canonical
Toolhub records. Common project-domain, database-name, and family-wildcard
aliases resolve to shared project anchors. A facet becomes selectable once two
tools cover at least two values; untagged nodes retain similarity forces instead
of being attracted to a synthetic `Other` group. Interactive maps use in-page forces up to 600 nodes;
larger layouts run in a same-origin browser Worker so the Toolforge webservice
only serves static assets and cached JSON.

Graph facets are materialized in `graph_tool_enrichment`. Official Toolhub
detail leads, official crawler payloads follow, matching self-hosted
`toolinfo.json` records may add missing values, and approved repository-analysis
suggestions have the lowest precedence. Producer jobs refresh affected tools
after their own transaction commits. The hourly `graph-enrichment` job is the
versioned repair backstop; it processes missing/failed rows locally, invalidates
derived graph cache entries only when facets change, and logs coverage,
platform leakage, compound technology values, retry counts, and materialization
status. It makes no upstream requests and stays within the standard 300-second
Toolforge job budget.

The `repository-analysis` job is the deterministic source-analysis layer. It
selects canonical Toolhub records with an HTTPS repository URL, checks the
remote HEAD SHA, and skips repositories whose SHA is already analyzed. New
tools enter automatically when their canonical record reaches the local cache;
changed repositories are revisited by oldest `checked_at` first. The worker
uses shallow non-recursive Git checkouts, removes symlinks before traversal,
does not execute repository code, caps the checkout and analyzer input, stores
only the redacted report, and records failures/backoff in
`repository_analysis_state`.

For the initial backfill, run a one-off job after deployment:

```sh
toolforge jobs run --wait 21600 --image python3.13 \
  --command '/usr/bin/env REPOSITORY_SCAN_LIMIT=10000 /data/project/toolhub-evolved/www/python/venv/bin/python /data/project/toolhub-evolved/repo/proxy/repository_scan.py' \
  repository-analysis-backfill
```

The regular hourly job continues the sweep afterwards. `repository_scan` is a
separate provenance label from maintainer-submitted source-analysis reports;
automated reports are deterministic and approved for the public health core,
while raw source and checkout contents are never stored.

Repository failures are recorded with exponential backoff and do not abort the
remaining candidates in the hourly batch. The people full pass and its
incremental queue share a MariaDB advisory lock so they cannot concurrently
replace the same Toolsadmin relationship evidence; a locked invocation exits cleanly and
the next scheduled run retries it.

## Logs

`~/uwsgi.log` and the per-job `~/<job>.out` / `~/<job>.err` files are appended
to indefinitely — successful runs, old tracebacks, and the guard's harmless
"already running; skipping" notices all accumulate. The nightly `rotate-logs`
job (`tools/rotate-logs.sh`, 03:05 UTC) caps them, keeping five gzipped
generations of anything past 8 MiB:

```sh
toolforge jobs logs rotate-logs          # what was rotated last night
ls -lh ~/uwsgi.log ~/uwsgi.log.*.gz      # live file plus archives
zcat ~/uwsgi.log.1.gz | less             # read the most recent archive
sh ~/repo/tools/rotate-logs.sh           # force a rotation now
```

Thresholds are `TOOLHUB_LOG_MAX_BYTES` and `TOOLHUB_LOG_KEEP`; point
`TOOLHUB_LOG_DIR` elsewhere to rehearse against a scratch directory.

Rotation copies and then truncates in place rather than renaming, because
uwsgi and the jobs framework hold these files open — a rename leaves them
writing to the rotated inode while the live path stays empty. The trade-off is
that log lines written during the copy are lost, which is why the job runs at
night rather than during a deploy. Rotation is a size cap, not retention: an
incident older than five generations of an 8 MiB file is gone, so pull what you
need out of `~/uwsgi.log` before the next nightly run.

## Backups & restore

Nightly `mariadb-dump` to `~/backups`, 14 dumps kept (`tools/backup-db.sh`).
Restore drill — do this once now, and after any schema change:

```sh
zcat ~/backups/<dump>.sql.gz | mariadb --defaults-file=$HOME/replica.my.cnf \
    -h tools.db.svc.wikimedia.cloud sXXXX__toolhub_evolved_restoretest
```

then point a local `TOOLHUB_DB_URL` at the restore-test DB and check
`/healthz` + `/v1/overlay/` shapes. Drop the test DB afterwards.

## Monitoring

- External uptime check (e.g. UptimeRobot free tier) on
  `https://<toolname>.toolforge.org/healthz` — it verifies DB reachability,
  not just the webservice.
- `webservice status` / `toolforge jobs list` for platform state;
  `~/uwsgi.log` for application errors (rotated nightly — see § Logs).
- The deploy script's post-restart smoke loop is the first line of defence —
  a deploy that doesn't serve the app fails the deploy, not the users.

## Incidents

| Symptom                          | First moves                                                                                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/healthz` returns 503           | ToolsDB reachability: `sql tools`; check `TOOLHUB_DB_URL`; `webservice restart`                                                                         |
| Site up, catalog empty           | Upstream Toolhub outage — the SPA shows "couldn't load live data"; nothing to do but wait/verify with `curl https://toolhub.wikimedia.org/api/ui/home/` |
| Sign-in loops to `/?login=error` | Check Toolhub OAuth env vars; callback URL exact? `TOOLHUB_EVOLVED_BASE_URL` needed? `toolhub.wikimedia.org` reachable?                                 |
| Official writes return 401       | The user's stored grant is absent/expired — ask them to sign in with Toolhub again                                                                      |
| Official writes return 4xx       | Toolhub rejected validation or permissions; check the response `details` from `/v1/write/*` and revise the payload                                      |
| Crawler failure emails           | `toolforge jobs logs crawler`; bad registered URL errors are recorded per-run in `crawler_runs`                                                         |
| Disk quota                       | `du -sh ~/backups ~/repo ~/*.log ~/*.out ~/*.err`; prune old backups; `sh ~/repo/tools/rotate-logs.sh`; `git -C ~/repo gc`                              |
