# Toolhub Evolved

A design **demonstrator** for a refreshed [Toolhub](https://toolhub.wikimedia.org/)
— the community catalog of Wikimedia tools. It is a dependency-free static
single-page app that runs on a fixed snapshot of the public Toolhub API, built to
explore how tool discovery could look and feel.

> This is a prototype, not the production site. All catalog data is real (a
> snapshot of the public API); a few clearly-labelled metrics are synthesized —
> see the **Experimental toggle** below.

![Home](docs/screenshots/hero-lean.png)

## Highlights

- **Discovery-first home** — search, persona shortcuts, featured tools, curated lists.
- **Faceted browse** (`#/search`) — filter by tool type & keywords, sort, paginate, shareable URLs.
- **Full tool pages** (`#/tools/:name`) — real metadata (wikis, languages, license, links) + related tools.
- **Footer & policy pages** — About, Help, Community, Privacy, Terms, Code of Conduct, API, Feeds.
- **Help maintain Toolhub** (`#/contribute`) — a hub linking source, tasks, translation and docs.
- **Wikimedia brand** — Montserrat + Source Serif 4, the 2022 brand palette, all in `tokens.css`.
- **Experimental toggle** — flip prospective features (popularity, health, reviews, …) on/off. Off = what's shippable against today's API. Each prospective feature is documented in code with what's missing (grep `EXPERIMENTAL`).
- **Accessible & responsive** — keyboard, focus management, AA contrast, no horizontal overflow at any width.

## Repository layout

```
public_html/        ← the deployable static site (web root on Toolforge)
  index.html        ·  app shell + hash router mount
  app.js            ·  router, views, rendering (vanilla JS, no framework)
  styles.css        ·  component styles (consume tokens only)
  tokens.css        ·  Wikimedia brand design tokens — single source of truth
  data.js           ·  generated snapshot (do not edit by hand)
tools/
  build_data.py     ·  regenerates public_html/data.js from API snapshots
  data/*.json       ·  raw Toolhub API snapshots
TOKENS.md           ·  design-token reference + contribution rules
docs/
  deploy-toolforge.md  ·  step-by-step Toolforge deployment
  screenshots/         ·  reference images
LICENSE             ·  GNU GPL v3.0-or-later
```

## Run locally

No build step — the data is inlined as a `<script>`.

```sh
# simplest: open the file directly
open public_html/index.html

# or serve over HTTP (needed for some browsers / to mirror Toolforge)
cd public_html && python3 -m http.server 8000
# → http://localhost:8000/
```

## Refresh the data snapshot

```sh
cd tools
# (re-fetch the *.json snapshots from the public API first; see build_data.py header)
python3 build_data.py     # writes ../public_html/data.js
```

## Deploy to Wikimedia Toolforge

See **[docs/deploy-toolforge.md](docs/deploy-toolforge.md)**. In short: create a tool,
clone this repo, point `~/public_html` at `public_html/`, and start a webservice —
the site is fully static so a lighttpd/PHP webservice serves it directly.

## License

GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE).

Catalog data shown is sourced from the Toolhub API and is released under CC0 by the
Wikimedia community; the Wikimedia brand assets follow the
[Wikimedia brand guidelines](https://meta.wikimedia.org/wiki/Brand).
