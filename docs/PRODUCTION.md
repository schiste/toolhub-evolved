<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Production Plan — Toolhub Evolved as a standalone product

Last updated: 2026-07-25. Companion to [`PLAN.md`](PLAN.md), which governed the
demonstrator. This document plans the step **`PLAN.md` §7 explicitly left out**:
turning the demonstrator into a real, standalone production service.

## 0. The decision this plan implements

- **Target: standalone product.** Toolhub Evolved becomes an independent
  production service — not a proposal to replace the official Toolhub frontend,
  and not a hardened demo. It gains its own backend, its own users, and its own
  data.
- **Scope: everything.** All Lane B simulations become real features: Wikimedia
  OAuth sign-in, favorites, lists CRUD, tool submit/edit, annotations, a
  server-side crawler, and search that includes locally-registered tools.
- **Hosting: Wikimedia Toolforge.** The product stays on Toolforge
  (`https://toolhub-evolved.toolforge.org/`), using Toolforge's webservice,
  ToolsDB, and Jobs framework.
- **Launch blocker: Lane A i18n/a11y must be finished first** (`PLAN.md`
  §2.2–2.3). Nothing user-facing launches before the interface is localizable
  and the deferred accessibility items are closed.

The demonstrator was deliberately built for this pivot: the write adapter
(`apiWrite`/`demoApi`) is shaped like Toolhub's real endpoints (`PLAN.md`
Appendix A), so productionizing is mostly **swapping the adapter's target from
`localStorage` to a real API** — callers, views, and the merge step stay as they
are.

## 1. Product architecture — "live base + owned overlay", now server-side

The core insight of the demonstrator carries over unchanged, one level up:

- **The base catalog stays live Toolhub data.** `apiGet` keeps reading
  `toolhub.wikimedia.org` through the same-origin read proxy. We do not fork or
  mirror the upstream catalog; upstream tools always render from live data.
- **Everything users do on this site lives in our own database.** Favorites,
  lists, tool submissions, field edits, annotation overrides, revision/audit
  rows — the exact deltas `demoOverlay` holds in `localStorage` today — move to
  a server-side store keyed by user, shared between browsers and visitors.
- **The merge step is unchanged.** `normalizeTool()`/`normalizeList()` still
  merge an overlay onto the live record at render time; the overlay now comes
  from `GET /v1/…` instead of `localStorage`.

This keeps the product honest by construction: our writes can never corrupt or
misrepresent upstream data, and the boundary between "live from Toolhub" and
"stored on this site" stays a first-class, labelable concept in the UI.

```
Browser (SPA, public_html/)
  │  GET /api/*   ──────────────►  read proxy ──► toolhub.wikimedia.org (live, read-only)
  │  GET/POST/PUT/DELETE /v1/* ──►  our API   ──► ToolsDB (MariaDB): users, favorites,
  │                                              lists, tools, annotations, revisions, audit
  └  GET /oauth/* ─────────────►  Wikimedia OAuth (meta.wikimedia.org)

Toolforge Jobs framework (scheduled)
  └  crawler job ──► fetches registered toolinfo.json URLs ──► validates ──► ToolsDB
```

### Components

| Component     | Choice                                                                                                                                 | Why                                                                                                     |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Web app       | Grow `proxy/app.py` into a small Flask package (blueprints)                                                                            | One Toolforge `python3.13` webservice already serves SPA + proxy; add a `/v1` blueprint, keep the stack |
| Database      | **ToolsDB (MariaDB)** + SQLAlchemy + Alembic migrations                                                                                | SQLite on Toolforge NFS is unsafe (locking); ToolsDB is the platform-native managed DB                  |
| Auth          | **Wikimedia OAuth 2.0** consumer (meta.wikimedia.org) + server session                                                                 | Real Wikimedia identity, natural on Toolforge; sessions in signed cookies backed by a DB session table  |
| Crawler       | **Toolforge Jobs framework** scheduled job (same repo, `tools/`)                                                                       | Server-side fetch of `toolinfo.json` (schema 1.2.2 validation) — the thing the browser never could      |
| Search        | Phase 1: **federated** (live upstream search + local DB search, merged) · Phase 2: Toolforge shared **Elasticsearch** if quota granted | Local tools become findable immediately without new infra; ES upgrades relevance later                  |
| Static assets | Unchanged (`dist/` build via `tools/deploy.sh`)                                                                                        | Already works                                                                                           |

### The two-catalog question (biggest product risk — decided up front)

A standalone catalog that accepts tool submissions inevitably diverges from the
official Toolhub. We defuse this rather than hide it:

1. **Provenance is always visible.** Every record renders its origin: _live from
   Toolhub_ vs. _registered on Toolhub Evolved_. Edits to upstream tools render
   as clearly-labeled community overlays, never as replacements.
2. **We publish, we don't fork.** Locally-registered tools are exposed as a
   public **`toolinfo.json` feed** (`/toolinfo.json`), so the _official_
   Toolhub crawler can ingest them. Toolhub Evolved becomes a feeder into the
   real ecosystem instead of a competing silo.
3. **Upstream courtesy.** Before launch we notify the Toolhub maintainers
   (Phabricator + tool talk page): what the service is, its User-Agent, expected
   API load, and the feed URL. The proxy already identifies itself and caches
   (30 s server TTL + 5 min browser); we keep respecting the API etiquette.

## 2. What changes in the frontend

Small, because the pivot was designed in:

- **`demoApi` → real API.** The write adapter's mode flag flips: `post/put/delete`
  call `/v1/*`; `localStorage` mode remains available for local dev and as the
  logged-out preview mode if we want to keep it.
- **Mock identity → real session.** The identity picker becomes "Sign in with
  Wikimedia"; `GET /v1/user/` drives the account menu. Logged-out users get the
  read-only interface (which, per `PLAN.md`, is complete on its own).
- **The experimental toggle retires from production semantics.** Features are no
  longer "prospective" — they're real. The red mockup banner and _Rules of
  Engagement_ page are rewritten into a plain **"About this site"** page: what's
  live from Toolhub, what's stored here, where your data lives, how to delete it.
  Signals we still can't source for real (health, usage, thanks counts from
  upstream tools) either ship from our own data (thanks given _on this site_ are
  real) or stay behind the toggle, still labeled synthetic.
- **Search UI** gains a provenance facet (Toolhub / registered here) driven by
  the federated search.

## 3. Phases

Estimates assume a solo maintainer; phases after P0 can overlap where noted.

### P0 — Launch blockers: finish Lane A i18n & a11y (~2 weeks) — BLOCKS EVERYTHING USER-FACING

Exactly `PLAN.md` §2.2–2.3, unchanged in content, promoted to blocker status:

- i18n phases 1–5: `i18n/en.json` + `t()` for shell/nav/cards, then detail/list
  pages, per-locale prose fragments, localized API-field selection, language
  switcher + pseudolocalization + RTL smoke test.
- Deferred a11y items: card grids as lists, crawler table `<caption>`/`scope`,
  card-as-link + separate quick-view button, disambiguated duplicate link
  destinations, per-field `lang`.

Exit gate: pseudolocale renders with zero hardcoded chrome strings; axe run
clean; the audit's remaining WCAG findings closed or explicitly waived.

### P1 — Backend foundation (~2 weeks; can start in parallel with P0)

- Restructure `proxy/` into an app package: `static` + `api-proxy` + `v1`
  blueprints; config from env; keep `app.py` as entrypoint (Toolforge contract).
- ToolsDB schema + Alembic: `users`, `sessions`, `favorites`, `lists`,
  `list_tools`, `tools` (locally registered), `tool_edits` (overlay on upstream
  names), `annotations`, `revisions`, `audit_log`, `crawler_urls`, `crawler_runs`.
- Wikimedia OAuth 2.0: register the consumer, `/oauth/login|callback|logout`,
  session cookie (HttpOnly, Secure, SameSite=Lax), CSRF token for all writes.
- Cross-cutting: per-user and per-IP rate limits on writes, input validation
  (reuse toolinfo 1.2.2 schema), structured logs, `/healthz`.
- Test story: the proxy tests extend to `/v1` (Flask test client + a throwaway
  MariaDB via container in CI); coverage gates stay at current thresholds.

Exit gate: sign in with a real Wikimedia account on Toolforge; session survives
restart; migrations run via a documented one-liner.

### P2 — First real features: favorites + lists (~1.5 weeks)

- `GET/POST /v1/user/favorites/`, `DELETE /v1/user/favorites/{name}/` — flip the
  adapter, `/favorites` now shared across the user's browsers.
- Lists CRUD (`/v1/lists/…`) with reorder; own lists render alongside live
  upstream lists, provenance-labeled.
- Every write appends `revisions`/`audit_log` rows; `/recent` and `/audit-logs`
  merge our rows over the live feeds (the P4 side-effect machinery lands here).

### P3 — Tool submit / edit / annotations (~2 weeks)

- `POST /v1/tools/` (net-new, required: `name`,`title`,`description`,`url`),
  `PUT /v1/tools/{name}/` — **adopting Toolhub's real permission rule**: core
  fields editable only on records with `origin="api"` (i.e., registered here);
  upstream/crawler-origin tools take **annotation edits only**
  (`PUT /v1/tools/{name}/annotations/`). This retires demo decision §8.4's
  "demo-friendly" laxity in favor of the faithful rule.
- Server-side render-time merge parity: detail pages, cards, and "my
  submissions" show owned records and annotation overlays with provenance
  labels.
- Publish the **`/toolinfo.json` feed** of locally-registered tools (§1.3).

### P4 — Crawler (~1.5 weeks)

- `/v1/crawler/urls/` CRUD (auth required) + `Add or remove tools` page goes
  real.
- Toolforge Jobs framework scheduled job (e.g. hourly): fetch each registered
  URL, validate against toolinfo 1.2.2, upsert `tools`, record `crawler_runs`
  with per-URL outcomes; surface runs on the existing `/crawler` history UI.
- Safety: request timeouts, response-size caps (mirror `_MAX_UPSTREAM_BYTES`),
  no redirects to private ranges, per-run URL budget.

### P5 — Search that includes our tools (~1–2 weeks)

- Phase 1 (launch): **federated search** — `/v1/search/tools/` queries ToolsDB
  (MariaDB FULLTEXT over name/title/description/keywords) and the SPA merges
  results with live `/api/search/tools/`, deduping by name (local edits
  decorate, local tools append). Facet counts for local tools computed in SQL.
- Phase 2 (post-launch): request Toolforge shared **Elasticsearch** credentials;
  index local records; if granted, move merging server-side for real relevance.

### P6 — Production hardening & launch (~1–2 weeks)

- **Security pass**: CSP recheck (connect-src still `'self'`), OAuth flows,
  CSRF, rate limits, gitleaks in CI already; add dependency audit job.
- **Ops runbook** (`docs/RUNBOOK.md`): deploy, rollback (git revert +
  `deploy.sh`), migration procedure, quota checks, "upstream API down" behavior.
- **Backups**: nightly Jobs-framework `mariadb-dump` of ToolsDB to the tool's
  home (NFS is replicated), 14-day rotation; documented restore drill (do one).
- **Monitoring**: external uptime check on `/healthz` (e.g. UptimeRobot free
  tier) + the existing post-deploy smoke loop in `tools/deploy.sh`; error log
  review cadence.
- **Policy & legal**: privacy policy rewritten for real server-side user data
  (what we store, retention, deletion — add self-serve account deletion);
  Toolforge rules & Wikimedia Cloud Services ToU compliance check; naming that
  cannot be mistaken for the official service (the existing "Evolved" suffix +
  "not the official Toolhub" line stays prominent).
- **Launch**: announce to Toolhub maintainers/Phabricator (per §1.3), then
  publicly.

**Total: ~10–12 weeks solo**, with P0∥P1 overlap. First user-visible production
milestone (real sign-in + favorites) lands ~4–5 weeks in.

## 4. Toolforge specifics & quotas

- Webservice: existing `python3.13` webservice; consider `webservice --replicas`
  if latency under load demands it (the TTL cache is per-worker — acceptable, or
  move it to Toolforge Redis when replicas > 1).
- ToolsDB: default quotas suffice for launch; monitor size, request increase if
  the crawler grows the catalog.
- Jobs framework: crawler + nightly backup jobs; both defined in-repo
  (`jobs.yaml`) so the full production config is versioned.
- Secrets (OAuth client secret, DB credentials): in the tool account's
  `~/.env`-style file readable only by the tool, never in the repo; documented
  in the runbook.
- Known platform limits accepted: no custom domain, shared-infra SLAs, ES access
  needs a quota request (hence federated search first).

## 5. Risks

| Risk                                                         | Mitigation                                                                                                                |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| Catalog divergence from official Toolhub                     | Provenance labeling everywhere + `/toolinfo.json` feeder feed (§1.3) — we add to the ecosystem                            |
| Upstream API changes/outage breaks the base catalog          | Already-graceful "couldn't load live data" states; proxy TTL cache absorbs blips; contract tests vs. `/api/schema/` in CI |
| Community perception (unofficial service using Toolhub data) | Early, explicit outreach to maintainers; honest naming; GPL-3.0 code; read-only, cached, identified API use               |
| Solo-maintainer ops burden                                   | Everything scripted and in-repo (deploy, jobs, migrations, backups); external uptime alerting; runbook                    |
| OAuth consumer approval latency (Wikimedia review)           | Register the consumer at the _start_ of P1, not the end                                                                   |
| ToolsDB/ES quota limits                                      | Federated-search fallback needs no ES; quota requests early with load estimates                                           |
| Spam/abuse once writes are real                              | Wikimedia-account gate, rate limits, audit log, admin delete path; new-account throttle if needed                         |

## 6. Explicit non-goals

- Replacing or upstreaming into the official Toolhub frontend (a separate
  endeavor with a separate process — nothing here precludes it later).
- Custom domain / off-Toolforge hosting (revisit only if Toolforge limits bite).
- Real-time usage/health/pageview signals for _upstream_ tools — still not
  obtainable; those stay labeled synthetic behind the toggle or are dropped.
- A write path to `toolhub.wikimedia.org` — never. All writes land in our DB.
