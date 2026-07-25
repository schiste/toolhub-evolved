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
| `TOOLHUB_OAUTH_CLIENT_ID`     | yes      | Wikimedia OAuth 2.0 consumer id (see below)                                                                     |
| `TOOLHUB_OAUTH_CLIENT_SECRET` | yes      | The consumer's secret                                                                                           |
| `TOOLHUB_DB_NAME`             | yes      | ToolsDB database name for backups, e.g. `sXXXX__toolhub_evolved`                                                |
| `TOOLHUB_BACKUP_DIR`          | no       | Backup destination (default `~/backups`)                                                                        |
| `TOOLHUB_INSECURE_COOKIES`    | no       | Set to `1` only for local http development — never in production                                                |

Without `TOOLHUB_DB_URL` the backend falls back to a repo-local SQLite file
(fine for development, unsafe on NFS under real traffic). Without the OAuth
vars, `/oauth/login` answers 503 and the site runs read-only + demo mode.

## OAuth consumer (one-time)

1. Propose a consumer at
   `https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration/propose`
   — OAuth **2.0**, confidential client, callback
   `https://<toolname>.toolforge.org/oauth/callback`, no extra grants needed
   (we only read the user's identity).
2. Store the id/secret via `toolforge envvars create` (never in the repo).
3. Wikimedia review can take days — file this before you need it.

## Database (ToolsDB)

- Create once: `sql tools` then `CREATE DATABASE sXXXX__toolhub_evolved;`
  (credentials come from `~/replica.my.cnf`).
- Schema: the app creates missing tables at startup (`Base.metadata.create_all`
  — idempotent, additive only). A column change needs a manual
  `ALTER TABLE` (write it down in the deploy notes) or a table rebuild; if
  migrations become frequent, introduce Alembic at that point.

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
| Sign-in loops to `/?login=error` | Check OAuth env vars; consumer approved? callback URL exact? meta.wikimedia.org reachable?                                                              |
| Crawler failure emails           | `toolforge jobs logs crawler`; bad registered URL errors are recorded per-run in `crawler_runs`                                                         |
| Disk quota                       | `du -sh ~/backups ~/repo`; prune old backups; `git -C ~/repo gc`                                                                                        |
