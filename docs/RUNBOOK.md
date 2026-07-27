<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Runbook — operating Toolhub Evolved in production

Companion to [`PRODUCTION.md`](PRODUCTION.md) (the plan) and
[`deploy-toolforge.md`](deploy-toolforge.md) (first-time setup). Everything here
runs as the tool account on Toolforge (`become <toolname>`).

## Configuration (env vars)

Set with `toolforge envvars create <NAME> <value>`; the webservice and jobs see
them automatically.

| Variable                         | Required | Meaning                                                                                                         |
| -------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `TOOLHUB_DB_URL`                 | yes      | SQLAlchemy URL for ToolsDB, e.g. `mysql+pymysql://sXXXX:PW@tools.db.svc.wikimedia.cloud/sXXXX__toolhub_evolved` |
| `TOOLHUB_SECRET_KEY`             | yes      | Stable random string (`python3 -c "import secrets;print(secrets.token_hex(32))"`) — signs session cookies       |
| `TOOLHUB_OAUTH_CLIENT_ID`        | yes      | Official Toolhub OAuth application client id (see below)                                                        |
| `TOOLHUB_OAUTH_CLIENT_SECRET`    | yes      | The Toolhub OAuth application's client secret                                                                   |
| `TOOLHUB_DB_NAME`                | yes      | ToolsDB database name for backups, e.g. `sXXXX__toolhub_evolved`                                                |
| `TOOLHUB_EVOLVED_BASE_URL`       | no       | Canonical public base URL used to build the OAuth callback, e.g. `https://<toolname>.toolforge.org`             |
| `TOOLHUB_EVOLVED_REVIEWER_USERS` | no       | Comma-separated Toolhub numeric ids or usernames promoted to the Evolved-only `reviewer` role on login          |
| `TOOLHUB_EVOLVED_ADMIN_USERS`    | no       | Comma-separated Toolhub numeric ids or usernames promoted to the Evolved-only `admin` role on login             |
| `TOOLHUB_API_BASE`               | no       | Toolhub base URL override for staging/tests; defaults to `https://toolhub.wikimedia.org`                        |
| `TOOLHUB_BACKUP_DIR`             | no       | Backup destination (default `~/backups`)                                                                        |
| `TOOLHUB_INSECURE_COOKIES`       | no       | Set to `1` only for local http development — never in production                                                |

Without `TOOLHUB_DB_URL` the backend falls back to a repo-local SQLite file
(fine for development, unsafe on NFS under real traffic). Without the OAuth
vars, `/oauth/login` answers 503 and the site runs with live reads plus
signed-out read-only mode. Without a stored per-user Toolhub grant, `/v1/write/*`
write endpoints answer 401 with `reauth: true`.

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

| Data                                         | Visibility                                      | Operational note                                                                                                                                                       |
| -------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `api_cache`                                  | Anonymous public Toolhub API payload cache      | Shared worker cache for `GET /api/*`; not canonical data, safe to clear, stale rows may be served only during transient upstream failures.                             |
| `users`                                      | Private account mapping                         | Local identity row derived from Toolhub OAuth and `GET /api/user/`; includes the Evolved-only `role`; delete with the user's Evolved account data.                     |
| `toolhub_tokens`                             | Secret                                          | Server-side Toolhub OAuth grant; never expose through `/v1`; rotate/delete on reconnect, logout-all, or account deletion.                                              |
| `favorites`                                  | Private per user                                | Cache/fallback only; official Toolhub favorite state wins after successful sync; new rows record `created_by_user_id`.                                                 |
| `lists`                                      | Private/user-visible fallback                   | Store local drafts or rejected official writes; keep official ids, creator, soft-delete, sync status, Toolhub response details, and validation errors.                 |
| `tools`                                      | Local draft or public Evolved feed row          | Never mirror official Toolhub tools; public local records require `review_status = approved` and feed `/toolinfo.json` for possible upstream ingestion.                |
| `tool_overlays`                              | User-visible local delta                        | Field patches for edits/annotations rejected by Toolhub or kept as drafts; strip canonical identity fields and keep Toolhub validation metadata.                       |
| `activity`                                   | User-visible/admin-visible depending on event   | Local audit/revision rows only; include local provenance and merge with live Toolhub feeds without pretending to be official Toolhub activity.                         |
| `crawler_urls`                               | Private until surfaced in local crawler UI/feed | Local URL registrations and official-write fallbacks; scheduled jobs fetch only enabled local URLs; failed official writes keep validation details.                    |
| `crawler_runs`                               | Operational/user-visible history                | Per-run crawler outcomes; useful for failure emails, user debugging, and restore checks.                                                                               |
| `tool_events`                                | Aggregate-only user-visible metrics             | Signed-in Evolved interactions; use only for privacy-limited aggregates and delete per-user rows on data deletion.                                                     |
| `tool_thanks`                                | Public aggregate, private user relation         | One active thanks per user/tool; counts include only `review_status = approved`, are labeled as Evolved data, and are deleted with the user's local data.              |
| `tool_health_targets` / `tool_health_checks` | Public checked status after approval            | Maintainer/user-provided targets stay hidden until `review_status = approved`; scheduled checks must use conservative timeouts and store errors without faking health. |
| `tool_media`                                 | Public only after approval                      | URL-based screenshots/media with license and source; pending rows are hidden until reviewed, labeled as Evolved data, and can be soft-deleted.                         |

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
sh ~/repo/tools/deploy.sh          # pull → build dist → restart → smoke-check
```

Rollback = `git -C ~/repo revert <sha>` (or `git reset --hard <good-sha>`)
followed by `sh ~/repo/tools/deploy.sh` again. The deploy script fails loudly
if the webservice doesn't come back healthy.

## Scheduled jobs

```sh
toolforge jobs load ~/repo/jobs.yaml   # crawler (hourly) + db-backup (nightly)
toolforge jobs list                    # status
toolforge jobs logs crawler            # last crawl output
```

The crawler exits non-zero (→ failure email) when any URL errored; per-run
results are also stored in the `crawler_runs` table.

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
  `~/uwsgi.log` for application errors.
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
| Disk quota                       | `du -sh ~/backups ~/repo`; prune old backups; `git -C ~/repo gc`                                                                                        |
