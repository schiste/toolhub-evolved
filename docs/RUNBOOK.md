<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Runbook — operating Toolhub Evolved in production

Companion to [`PRODUCTION.md`](PRODUCTION.md) (the plan) and
[`deploy-toolforge.md`](deploy-toolforge.md) (first-time setup). Everything here
runs as the tool account on Toolforge (`become <toolname>`).

## Configuration (env vars)

Set with `toolforge envvars create <NAME> <value>`; the webservice and jobs see
them automatically.

| Variable                      | Required | Meaning                                                                                                         |
| ----------------------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `TOOLHUB_DB_URL`              | yes      | SQLAlchemy URL for ToolsDB, e.g. `mysql+pymysql://sXXXX:PW@tools.db.svc.wikimedia.cloud/sXXXX__toolhub_evolved` |
| `TOOLHUB_SECRET_KEY`          | yes      | Stable random string (`python3 -c "import secrets;print(secrets.token_hex(32))"`) — signs session cookies       |
| `TOOLHUB_OAUTH_CLIENT_ID`     | yes      | Official Toolhub OAuth application client id (see below)                                                        |
| `TOOLHUB_OAUTH_CLIENT_SECRET` | yes      | The Toolhub OAuth application's client secret                                                                   |
| `TOOLHUB_DB_NAME`             | yes      | ToolsDB database name for backups, e.g. `sXXXX__toolhub_evolved`                                                |
| `TOOLHUB_EVOLVED_BASE_URL`    | no       | Canonical public base URL used to build the OAuth callback, e.g. `https://<toolname>.toolforge.org`             |
| `TOOLHUB_API_BASE`            | no       | Toolhub base URL override for staging/tests; defaults to `https://toolhub.wikimedia.org`                        |
| `TOOLHUB_BACKUP_DIR`          | no       | Backup destination (default `~/backups`)                                                                        |
| `TOOLHUB_INSECURE_COOKIES`    | no       | Set to `1` only for local http development — never in production                                                |

Without `TOOLHUB_DB_URL` the backend falls back to a repo-local SQLite file
(fine for development, unsafe on NFS under real traffic). Without the OAuth
vars, `/oauth/login` answers 503 and the site runs with live reads plus
browser-local demo mode. Without a stored per-user Toolhub grant, `/v1/toolhub/*`
write endpoints answer 401 with `reauth: true`.

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

| Data             | Visibility                                      | Operational note                                                                                                          |
| ---------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `users`          | Private account mapping                         | Local identity row derived from Toolhub OAuth and `GET /api/user/`; delete with the user's Evolved account data.          |
| `toolhub_tokens` | Secret                                          | Server-side Toolhub OAuth grant; never expose through `/v1`; rotate/delete on reconnect, logout-all, or account deletion. |
| `favorites`      | Private per user                                | Cache/fallback only; official Toolhub favorite state wins after successful sync.                                          |
| `lists`          | Private/user-visible fallback                   | Store local drafts or rejected official writes; keep official ids and sync status as the schema grows.                    |
| `tools`          | Local draft or public Evolved feed row          | Never mirror official Toolhub tools; public local records feed `/toolinfo.json` for possible upstream ingestion.          |
| `tool_overlays`  | User-visible local delta                        | Field patches for edits/annotations rejected by Toolhub or kept as drafts; label provenance in the UI.                    |
| `activity`       | User-visible/admin-visible depending on event   | Local audit/revision rows only; merge with live Toolhub feeds without pretending to be official Toolhub activity.         |
| `crawler_urls`   | Private until surfaced in local crawler UI/feed | Local URL registrations and official-write fallbacks; scheduled jobs fetch only enabled local URLs.                       |
| `crawler_runs`   | Operational/user-visible history                | Per-run crawler outcomes; useful for failure emails, user debugging, and restore checks.                                  |

Before adding a new Evolved-only table, document the owner, purpose,
visibility, retention/deletion behavior, export behavior, Toolhub handoff path,
abuse controls, and backup/restore impact in the feature plan and this runbook.

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
| Official writes return 4xx       | Toolhub rejected validation or permissions; check the response `details` from `/v1/toolhub/*` and revise the payload                                    |
| Crawler failure emails           | `toolforge jobs logs crawler`; bad registered URL errors are recorded per-run in `crawler_runs`                                                         |
| Disk quota                       | `du -sh ~/backups ~/repo`; prune old backups; `git -C ~/repo gc`                                                                                        |
