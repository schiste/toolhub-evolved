# Deploying to Wikimedia Toolforge

Toolforge Evolved is a **static** site (HTML/CSS/JS only — the data is baked into
`public_html/data.js`). It uses **hash routing** (`#/...`) and **relative** asset
paths, so it works under any base URL with no server-side rewrites. The simplest
way to host it is a lighttpd/PHP webservice serving `~/public_html`.

## Prerequisites

- A [Wikimedia developer account](https://www.mediawiki.org/wiki/Developer_access).
- Membership in a Toolforge **tool** account. Create one at
  [toolsadmin.wikimedia.org](https://toolsadmin.wikimedia.org/) — e.g. a tool named
  `toolhub-evolved`, served at `https://toolhub-evolved.toolforge.org/`.

## First-time deploy

```sh
# 1. SSH in and become the tool
ssh <your-shell-name>@login.toolforge.org
become toolhub-evolved        # use your tool's name

# 2. Clone the repository into the tool's home
git clone https://github.com/schiste/toolhub-evolved.git ~/repo

# 3. Point the served web root at the repo's public_html
#    (the webservice serves ~/public_html by default)
rm -rf ~/public_html
ln -s ~/repo/public_html ~/public_html

# 4. Start the webservice (static files are served directly by lighttpd)
webservice --backend=kubernetes php8.2 start

# 5. Visit https://<toolname>.toolforge.org/
```

## Updating after a change

```sh
become toolhub-evolved
cd ~/repo && git pull
webservice restart
```

A convenience script is provided: `bash ~/repo/tools/deploy.sh`.

## Notes & options

- **Why the PHP webservice for a static site?** Toolforge's `php8.2` webservice runs
  lighttpd, which serves static files from `~/public_html` directly. No PHP is
  executed; it's just the easiest static host on the platform.
- **Build service alternative.** Toolforge's buildpack-based build service can also
  serve this; for a static SPA the lighttpd path above is simpler and has no build
  step, so it's recommended here.
- **Fonts & privacy.** `index.html` loads Montserrat and Source Serif 4 from Google
  Fonts. For a privacy-respecting production deploy, self-host those WOFF2 files
  under `public_html/fonts/` and update the `@font-face`/`<link>` references.
- **Data freshness.** The catalog is a snapshot. To refresh, run
  `tools/build_data.py` (after re-fetching the API snapshots) and commit the new
  `public_html/data.js`.
