# Toolhub Evolved

A companion interface for [Toolhub](https://toolhub.wikimedia.org/) — the
community catalog of Wikimedia tools. It reads **live Toolhub data** from the
public API, adds an Evolved overlay for extra/local data, and can publish
supported writes back to official Toolhub when users sign in with Toolhub OAuth.

> This runs next to Toolhub, not instead of it. Official Toolhub remains the
> catalog source of truth; Evolved stores only complementary overlay data,
> drafts/fallbacks, and real Evolved-owned data that Toolhub does not expose;
> public Evolved-owned records are labeled and review-gated before broad
> visibility.

![Home](docs/screenshots/hero-lean.png)

## Highlights

- **Discovery-first home** — search, persona shortcuts, featured tools, curated lists.
- **Faceted browse** (`/search`) — live Elasticsearch facets (tool type, keywords, audience, language, license, wiki), sort, paginate, shareable URLs.
- **Full tool pages** (`/tools/:name`) — real metadata (wikis, languages, license, links) + related tools, real revision history.
- **API explorer** (`/api-docs`) — curated read-only endpoint forms, formatted JSON responses, and copyable `curl`/`fetch` examples.
- **Source code analysis** (`/my-tools`) — maintainer-submitted source bundles produce redacted, evidence-backed project/API/access/dependency/OAuth suggestions.
- **User-script directory** (`/userscripts`) — the distinct scripts hiding in a wiki's user space, folded out of their per-user copies and ranked by how many people load them.
- **Footer & policy pages** — About, Help, Community, Privacy, Terms, Code of Conduct, API, Feeds.
- **Help maintain Toolhub** (`/contribute`) — a hub linking source, tasks, translation and docs.
- **Wikimedia brand** — Montserrat + Source Serif 4, the 2022 brand palette, all in `tokens.css`.
- **Always-on Evolved layer** — official-first writes, local drafts/fallback overlays, and Evolved-owned signals when they are backed by real data.
- **Accessible & responsive** — keyboard, focus management, AA contrast, no horizontal overflow at any width.

## Architecture

The Toolhub API sends **no CORS headers**, so the browser can't call it directly
from another origin. The Flask app (`proxy/app.py`) serves everything from one
origin:

1. Serves the static SPA from `public_html/`.
2. Reverse-proxies read-only `GET /api/*` to `toolhub.wikimedia.org/api/*`.
3. Hosts the production backend (`proxy/backend/`): Toolhub OAuth sign-in,
   server-side storage of the user's official Toolhub grant, the `/v1/overlay/*`
   API for Evolved-local data, and the `/v1/write/*` official-first lifecycle
   that validates locally, checks Evolved policy, attempts Toolhub, and stores
   sync/fallback metadata. Upstream catalog data is never mirrored: if a record
   exists on Toolhub, the live API is its source of truth and our database only
   holds the delta (see
   [`docs/PRODUCTION.md`](docs/PRODUCTION.md)).

The SPA (`public_html/main.js`, `public_html/views/`, and `public_html/lib/`) fetches everything live through `/api/…` — there is
no bundled catalog. Live endpoints used: `/api/search/tools/` (faceted),
`/api/tools/{name}/`, `/api/tools/{name}/revisions/`, `/api/lists/`, `/api/users/`,
`/api/recent/`, `/api/auditlogs/`, `/api/crawler/runs/`, `/api/ui/home/`.

Signed-out users get live Toolhub reads only. Signed in with Toolhub,
localStorage acts as a synchronous cache of the server overlay: it is pulled from
`GET /v1/overlay/` at boot and overlay mutations write through with
`PUT /v1/overlay/<key>`. Supported create/update/delete actions first call the
backend lifecycle through `/v1/write/*`; when Toolhub rejects a supported
draftable write, Evolved stores a local fallback with Toolhub validation details
so the user's work is not lost.

Maintainers can also run deterministic source-code analysis from `/my-tools` or
from the CLI:

```sh
PYTHONPATH=proxy python proxy/analyze_source.py path/to/tool --tool-name my-tool
```

The analyzer reads local text source files, extracts Wikimedia projects, API
usage, access rights, the concrete endpoints it calls (host, path, and the API
action where there is one), external dependencies, lockfile evidence, OAuth
scopes, technology, repository context, and review warnings, then emits deterministic
assessment scores with evidence-backed recommendations. Raw source files are not
stored.

## MCP server

Toolhub Evolved exposes catalog discovery as a stateless HTTP MCP server for use
in LLM-based workflows. Any MCP-capable client can add the endpoint and access
four tools plus a prior-art-review prompt. The public
[`/mcp-server`](https://toolhub-evolved.toolforge.org/mcp-server) guide includes
separate, verified setup examples for Claude Code, Visual Studio Code, Cursor,
and raw HTTP.

```bash
claude mcp add --transport http toolhub-discovery https://toolhub-evolved.toolforge.org/mcp
```

**Tools** — all read-only, no authentication:

- **`search_tools(query, limit=10)`** — relevance-ranked search across the latest complete local Toolhub catalog generation. Keep queries short (2-3 content words).
- **`facet_tools(...)`** — filter tools by technical signals (`dependency`, `api`, `detected_technology`) or declared catalog metadata (`declared_technology`, `tool_type`, `keyword`, `wiki`, `license`, `ui_language`, `task`, `audience`). Results include adoption counts; legacy `technology` remains an alias for `detected_technology`.
- **`list_facet_values(type)`** — list distinct values of one facet type, adoption-ranked. Call before `facet_tools` to learn what values exist.
- **`get_tool(name)`** — fetch one tool's full canonical Toolhub record by exact name.

**Prompt**:

- **`prior-art-review`** — guided workflow to evaluate greenfield tool ideas. The prompt characterizes the idea, retrieves via search and facets, and reports findings in three sections: build/reuse/differentiate, adjacent tools, and recommended stack (ranked by adoption). Includes caveat instructions about coverage and facet limitations.

The endpoint speaks both legacy `initialize`-handshake protocol (2025-06-18 and earlier) and the newer 2026-07-28 stateless revision. Rate-limited to 60 requests per rolling minute per client IP; no session cookies and no request-time Toolhub call. See [`docs/deploy-toolforge.md`](docs/deploy-toolforge.md) for deployment notes and conformance testing with the official MCP inspector.

**Claude skill** — [`skills/toolhub-discovery/`](skills/toolhub-discovery/) holds an optional skill for Claude Code and claude.ai. It is deliberately thin: the review methodology lives in the `prior-art-review` prompt above, so it reaches every MCP client and has one place to be corrected. What the skill adds is the part a prompt cannot do — it fires on its own when someone starts describing a tool idea, rather than waiting to be invoked by a user who already knows to check. Copy the directory into `~/.claude/skills/` to install it; the MCP server must be configured first.

**Toolhub creation skill** — [`skills/toolhub-creation/`](skills/toolhub-creation/) is a portable agent skill for creating, migrating, and validating repository-owned `toolinfo.json`. It enforces the `toolforge-$PROJECT` naming convention, structured author identities, the core-versus-annotation boundary, and schema 1.2.2 with an offline helper. Copy the directory into the skills location supported by your agent runtime (for example `~/.claude/skills/` or `$CODEX_HOME/skills/`).

## Repository layout

```
public_html/        ← the static single-page app (served by the proxy)
  index.html        ·  app shell + router mount
  main.js           ·  app boot, link interception, event wiring
  views/            ·  route views and rendering logic
  lib/              ·  shared core, atoms, molecules, and organisms
  styles/           ·  component styles and Wikimedia brand design tokens
proxy/
  app.py            ·  Flask: serves the SPA + read-only /api proxy to Toolhub
  requirements.txt  ·  Flask + requests
tools/
  deploy.sh         ·  Toolforge update helper
TOKENS.md           ·  design-token reference + contribution rules
docs/
  I18N.md              ·  source-message rules and translatewiki readiness notes
  FEATURES.md          ·  generated feature listing from public_html/views/experiments.js
  HYBRID-FEATURE-PLAN.md · feature-by-feature backend realization plan
  PLAN.md              ·  the comprehensive roadmap (ship lane + experiments lane)
  AUDIT-i18n-a11y.md   ·  detailed i18n / accessibility findings
  deploy-toolforge.md  ·  step-by-step Toolforge deployment
  USERSCRIPTS.md       ·  the user-space script census, collapse rules, and directory
  screenshots/         ·  reference images
LICENSE             ·  GNU GPL v3.0-or-later
```

## Roadmap

See **[docs/PLAN.md](docs/PLAN.md)** for the original demonstrator roadmap and
**[docs/PRODUCTION.md](docs/PRODUCTION.md)** for the production architecture.
The current direction is hybrid: official Toolhub remains the catalog source of
truth, scheduled jobs publish complete generations into Evolved's local read
replica, supported signed-in writes use official Toolhub OAuth, and Evolved
keeps a local overlay for drafts, fallback state, and features the official API
does not expose. The feature-by-feature realization plan lives in
**[docs/HYBRID-FEATURE-PLAN.md](docs/HYBRID-FEATURE-PLAN.md)**.

## Run locally

The app needs the proxy running (so `/api/*` resolves and CORS is avoided):

```sh
cd proxy
python3 -m venv venv && venv/bin/pip install -r requirements.txt
export TOOLHUB_INSECURE_COOKIES=1   # local dev over http: relax Secure cookies
venv/bin/python app.py
# → http://localhost:8000/   (serves the SPA and proxies /api to Toolhub)
```

`TOOLHUB_INSECURE_COOKIES=1` marks the process as local development. Without it
the app refuses to start unless `TOOLHUB_SECRET_KEY` is set, so a production
deployment can never fall back to a per-process session key (see
[docs/RUNBOOK.md](docs/RUNBOOK.md)).

To test signed-in Evolved pages without a real Toolhub OAuth application, enable
the loopback-only development sign-in before starting Flask:

```sh
export TOOLHUB_DEV_LOGIN=1
export TOOLHUB_DEV_USERNAME=Schiste   # optional display name
```

Then open `/oauth/dev-login?next=/my-tools` on `localhost` or `127.0.0.1`. This
creates only an Evolved-local session; official Toolhub writes remain disabled
until you sign in through real Toolhub OAuth.

## Deploy to Wikimedia Toolforge

See **[docs/deploy-toolforge.md](docs/deploy-toolforge.md)**. In short: create a tool,
clone this repo, point the `python3.13` webservice entrypoint at `proxy/`, build the
virtualenv inside the runtime image, and start the webservice.

## Quality gates

Every push runs the full suite in CI (`.github/workflows/ci.yml`):

Run `npm run preflight` before the expensive suites. It executes independent
static, hygiene, secret, and available Python checks concurrently, reports all
deterministic failures together, and leaves Vitest/pytest/Playwright for one
final verification pass after those issues are fixed.

- **Formatting / lint** — Prettier, ESLint (architecture-boundary rules + license
  headers, zero warnings), Stylelint (design-token enforcement), cspell.
- **Types** — `tsc --checkJs` in **full strict mode** across the whole app.
- **Tests** — Vitest (happy-dom), with a V8 **coverage gate** (statements ≥ 96 %,
  branches ≥ 90 %, functions ≥ 98 %, lines ≥ 97 %); Playwright e2e (smoke +
  axe accessibility).
- **Hygiene** — knip (dead code), jscpd (duplication), a small AST checker
  (`tools/checks.mjs`: XSS, a11y, dead code, floating promises, HTML balance),
  `npm run i18n:check`, a JS payload budget, and gitleaks secret scanning.
- **Proxy** — ruff (`select = ALL`, incl. flake8-bandit security), pip-audit,
  and a pytest asserting the CSP + security headers.

**Mutation testing** (Stryker) runs nightly (`.github/workflows/mutation.yml`)
at a **literal 100 % score** over `public_html/**`. The handful of genuinely
equivalent mutants carry documented `// Stryker disable` comments — the project's
only in-code suppressions — indexed in [EQUIVALENTS.md](EQUIVALENTS.md).

## Local hooks

The hooks live in `.githooks/`, not `.git/hooks/`, so git has to be pointed at
them once per clone:

```sh
npm run hooks:install
```

That sets `core.hooksPath`, installs the npm and Playwright dependencies, and
builds `.quality/python` from the same pinned requirements CI uses. Afterwards
`pre-commit` runs lint-staged over the staged files and `pre-push` runs eslint,
prettier, the AST checks, and the feature-doc freshness check.

### Aethyme broker (optional)

Several AI agent sessions sometimes share this working tree. The Aethyme broker
coordinates them, and two pieces of it are committed: the policy in
`.aethyme/config.toml` and `.aethyme/gates.toml`, and a shim in
`.githooks/pre-commit` that runs the gates matching your staged files and blocks
the commit when one fails. The shim resolves `aethyme` from `PATH`, so
contributors without it installed are skipped entirely — nothing to opt out of.

The agent-facing half is deliberately **not** committed. `aethyme enhance deploy`
bakes an absolute path to your local Aethyme checkout into `AGENTS.md`,
`CLAUDE.md`, and the `.claude/`/`.codex/` skills, and `aethyme enhance verify`
rejects hand-edits to them, so they cannot be made portable. They are gitignored;
generate your own instead:

```sh
aethyme init                      # idempotent: writes/validates broker policy
aethyme enhance deploy --repo .   # generates AGENTS.md + the agent skills
aethyme certify                   # read-only: reports whether setup is intact
```

Agents then take an isolated worktree with
`aethyme broker start --task "<task>"` and merge it back through the gates with
`aethyme broker submit --session <id>`, rather than editing this checkout
directly.

## License

GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE).

Catalog data shown is sourced from the Toolhub API and is released under CC0 by the
Wikimedia community; the Wikimedia brand assets follow the
[Wikimedia brand guidelines](https://meta.wikimedia.org/wiki/Brand).
