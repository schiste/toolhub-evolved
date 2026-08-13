# Deploying to Wikimedia Toolforge

Toolhub Evolved runs as a small **Python (Flask) webservice** that does two things
(`proxy/app.py`):

1. Serves the static single-page app from `public_html/`.
2. Reverse-proxies read-only `GET /api/*` to the live Toolhub API
   (`toolhub.wikimedia.org`) **same-origin**, so the browser can read live
   catalog data without hitting CORS (the upstream API sends no CORS headers).
3. Hosts `/v1/*`: Evolved's overlay API and the `/v1/write/*` official-first
   lifecycle that performs Toolhub writes with the signed-in user's OAuth grant
   and stores Evolved fallback metadata when appropriate.

The tool graph remains compatible with the same single Python webservice: graph
payloads and cache entries are generated server-side, while maps above 600 nodes
settle in a versioned same-origin browser Worker using Barnes-Hut repulsion. The
worker is copied into `dist/` by the existing pure-Python production build and
is allowed explicitly by the strict `worker-src 'self'` CSP directive.

The app uses clean History API routes (`/search`, `/tools/:name`, etc.). The
Flask webservice serves real files when present and falls back to `index.html`
for non-API paths, and the app shell uses root-relative assets so direct loads
and refreshes work on every app route.

## Prerequisites

- A [Wikimedia developer account](https://www.mediawiki.org/wiki/Developer_access).
- A Toolforge **tool** account (e.g. `toolhub-evolved`), created at
  [toolsadmin.wikimedia.org](https://toolsadmin.wikimedia.org/), served at
  `https://toolhub-evolved.toolforge.org/`.

## First-time deploy

```sh
ssh login.toolforge.org
become toolhub-evolved

# 1. Clone the repo
git clone https://github.com/schiste/toolhub-evolved.git ~/repo

# 2. Point the python webservice entrypoint at proxy/
mkdir -p ~/www/python
ln -sfn ~/repo/proxy ~/www/python/src

# 3. Build the virtualenv INSIDE the runtime image (bastions can't create venvs).
#    Either run these in `webservice python3.13 shell`, or non-interactively:
webservice python3.13 shell -- bash -lc '\
  python3 -m venv ~/www/python/venv && \
  ~/www/python/venv/bin/pip install -r ~/repo/proxy/requirements.txt'

# 4. Start the webservice
webservice python3.13 start

# → https://<toolname>.toolforge.org/
```

## Production backend (database, sign-in, crawler)

The webservice also hosts the site's own backend (`proxy/backend/`): Toolhub
OAuth sign-in, local overlay storage, and official Toolhub write forwarding.
It activates fully once configured:

1. Create the ToolsDB database and set the env vars (`TOOLHUB_DB_URL`,
   `TOOLHUB_SECRET_KEY`, `TOOLHUB_OAUTH_CLIENT_ID`,
   `TOOLHUB_OAUTH_CLIENT_SECRET`, `TOOLHUB_DB_NAME`) with
   `toolforge envvars create` — the full table and the Toolhub OAuth steps
   are in [`RUNBOOK.md`](RUNBOOK.md).
   Set `TOOLHUB_EVOLVED_BASE_URL=https://<toolname>.toolforge.org` if the
   callback URL needs to be forced. Optional
   `TOOLHUB_EVOLVED_REVIEWER_USERS` and `TOOLHUB_EVOLVED_ADMIN_USERS` env vars
   can promote Toolhub-authenticated users into Evolved-only reviewer/operator
   roles without granting them any additional official Toolhub rights.
2. Load the scheduled jobs (hourly crawler, six-hourly Toolhub catalog
   `toolinfo.json` discovery, six-hourly official crawler source indexing,
   six-hourly complete official-account projection, minutely cache
   invalidator/prewarmer, nightly backup):
   `toolforge jobs load ~/repo/jobs.yaml`.
   Deploys also finish a safe account-projection generation and run one cache
   invalidation/prewarm pass before the webservice restart. If the account
   refresh fails, the deploy stops before restart and the last complete account
   generation remains intact.

Unconfigured, the site still runs — live read interface plus signed-out read-only
mode, with `/oauth/login` answering 503 and official write endpoints returning
`reauth: true` until the user has a stored Toolhub grant.

## Configuring ProxyFix for rate limiting

Rate limiting on faceted discovery endpoints (`/v1/facets/tools/` and
`/v1/facets/values/`) uses `request.remote_addr` to identify clients. Behind
Toolforge's ingress, this is always the proxy's address unless ProxyFix is
configured — without it, one global bucket limits the entire tool to 120 requests
per minute.

**To measure and enable ProxyFix:**

1. Open `https://toolhub-evolved.toolforge.org/v1/debug/forwarded/` **from a
   signed-in browser session** on a machine whose public IP you know (the route is
   `@login_required`, so an unauthenticated curl gets a redirect and a misleading
   result). The response shows `candidates` — possible hop counts.

2. Look for the row where `address` matches your known public IP (the route's
   docstring explains which column each hop count produces). Note that row's `hops`
   value.

3. Set the environment variable `TOOLHUB_PROXYFIX_X_FOR=<hops>` in the tool
   account's env file via `toolforge envvars edit` (see `RUNBOOK.md`).

4. Delete `/v1/debug/forwarded/` to remove the temporary debug route (see its
   docstring for the `@app.route` line to remove from `proxy/backend/v1.py`).

5. Restart the webservice: `webservice restart`.

Test: after restart, visit `/v1/debug/forwarded/` again from the same IP. It
should now show `403 Forbidden` (the route is no longer registered). The rate
limiter is now active.

## Updating after a change

```sh
become toolhub-evolved
cd ~/repo && git pull
webservice restart            # or: sh ~/repo/tools/deploy.sh
```

(Only re-run step 3 when `proxy/requirements.txt` changes.)

## Notes

- **Read-only proxy.** `proxy/app.py` only ever forwards `GET` to
  `toolhub.wikimedia.org/api/...`. It is not an open proxy and performs no writes.
- **Official writes.** Authenticated create/update/delete flows call
  `/v1/write/*`; the backend validates locally, checks Evolved policy, attaches
  the stored Toolhub OAuth access token, and forwards to official `/api/*`.
  Tokens are never exposed to the SPA.
- **Live endpoints used:** `/api/tools/`, `/api/tools/{name}/`,
  `/api/search/tools/` (faceted), `/api/lists/`, `/api/users/`, `/api/recent/`,
  `/api/auditlogs/`, `/api/crawler/runs/`, `/api/ui/home/`.
- **Pagination:** upstream `next`/`previous` are absolute `toolhub.wikimedia.org`
  URLs; the SPA paginates with `?page=` through the proxy instead of following them.
- **No bundled catalog.** The SPA does not ship a catalog snapshot in `dist/`.
  User-facing reads remain live through the proxy, while the server-side
  `canonical_tool_cache` supports background enrichment and resilience. If the
  API is unreachable, views show a clear "Couldn't load live data" message
  rather than presenting the local enrichment cache as canonical.
- **Fonts & privacy.** Typography uses the native Wikimedia/Codex system font stack
  (`styles/tokens.css`); no web font is downloaded, so the app makes no third-party
  font requests at all.
