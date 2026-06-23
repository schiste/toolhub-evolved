# Deploying to Wikimedia Toolforge

Toolhub Evolved runs as a small **Python (Flask) webservice** that does two things
(`proxy/app.py`):

1. Serves the static single-page app from `public_html/`.
2. Reverse-proxies read-only `GET /api/*` to the live Toolhub API
   (`toolhub.wikimedia.org`) **same-origin**, so the browser can read live
   catalog data without hitting CORS (the upstream API sends no CORS headers).

The app uses hash routing (`#/…`) and relative asset paths, so it works under any
base URL with no rewrite rules.

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
- **Live endpoints used:** `/api/tools/`, `/api/tools/{name}/`,
  `/api/search/tools/` (faceted), `/api/lists/`, `/api/users/`, `/api/recent/`,
  `/api/auditlogs/`, `/api/crawler/runs/`, `/api/ui/home/`.
- **Pagination:** upstream `next`/`previous` are absolute `toolhub.wikimedia.org`
  URLs; the SPA paginates with `?page=` through the proxy instead of following them.
- **No bundled catalog.** The SPA reads everything live through the proxy; there is
  no snapshot to fall back to. If the API is unreachable, views show a clear
  "Couldn't load live data" message rather than stale data.
- **Fonts & privacy.** `index.html` loads Montserrat / Source Serif 4 from the
  Wikimedia FontCDN (`tools-static.wmflabs.org/fontcdn`, a Google-Fonts proxy), so
  no third-party requests are made to Google.
