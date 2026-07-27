<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Production Plan — Toolhub Evolved beside Toolhub

Last updated: 2026-07-27. Companion to [`PLAN.md`](PLAN.md), which governed the
demonstrator. This document captures the current production target: run Evolved
beside official Toolhub, using live Toolhub data and APIs while storing only the
additional Evolved layer locally.

For the feature-by-feature plan that turns the Evolved layer into real backend
features, see [`HYBRID-FEATURE-PLAN.md`](HYBRID-FEATURE-PLAN.md).

## 0. The decision this plan implements

- **Target: side-by-side product.** Toolhub Evolved runs as an independent
  interface next to official Toolhub, not as a replacement frontend and not as a
  competing catalog.
- **Scope: hybrid writes.** Supported signed-in actions use official Toolhub's
  OAuth server and write to official Toolhub's API first: favorites, lists
  CRUD, direct tool create/update/delete, annotations, and crawler URL
  registration. Evolved keeps local fallback/draft/overlay data for rejected
  writes and for features Toolhub does not expose.
- **Hosting: Wikimedia Toolforge.** The product stays on Toolforge
  (`https://toolhub-evolved.toolforge.org/`), using Toolforge's webservice,
  ToolsDB, and Jobs framework.
- **Launch blocker: Lane A i18n/a11y must be finished first** (`PLAN.md`
  §2.2–2.3). Nothing user-facing launches before the interface is localizable
  and the deferred accessibility items are closed.
- **Data architecture (updated 2026-07-27): live Toolhub + local overlay.**
  All Toolhub catalog data is read **live from the Toolhub API** — it is never
  mirrored, synced, or copied into our database as canonical catalog state. A
  short-lived `api_cache` table may store anonymous `GET /api/*` response bodies
  only as a shared performance cache with expiry/stale metadata; the browser may
  also keep a bounded localStorage copy of anonymous `/api/*` payloads so hard
  refreshes can render stale public data while a live refresh runs. Official
  writes are sent to Toolhub's API with the user's stored Toolhub OAuth grant. The
  **project-specific database complements** Toolhub: local users mapped to
  Toolhub identities, stored OAuth grants, sessions, drafts/fallback overlays,
  Evolved-only state, API cache rows, and revision/audit rows for local actions.
  If a record exists upstream, the API is its source of truth.

The demonstrator was deliberately built for this pivot: the write adapter
(`apiWrite`/`demoApi`) is shaped like Toolhub's real endpoints (`PLAN.md`
Appendix A), so productionizing is mostly **swapping the adapter's target from
`localStorage` to a real API** — callers, views, and the merge step stay as they
are.

### Implementation status (2026-07-27)

Landed in this repo (see the runbook for the Toolforge configuration steps):

- **Backend** (`proxy/backend/`): ToolsDB/SQLite via SQLAlchemy, official
  Toolhub OAuth 2.0, stored per-user Toolhub grants, sessions + CSRF + rate
  limiting, the `/v1` overlay API, `/v1/write/*` official-first lifecycle,
  `/v1/search/tools/`, `/v1/moderation/public-data/`, `/healthz`, and the
  `/toolinfo.json` feeder feed. The lower level `/v1/toolhub/*` bridge remains
  available for compatibility and smoke checks.
- **Author verification**: `proxy/backend/author_claims.py` powers the signed-in
  My tools resolver. It starts from the Toolhub OAuth username, searches official
  Toolhub author data, records display-name matches as unverified, and upgrades
  claims only through stronger Evolved evidence: public Toolsadmin maintainer
  pages, successful official Toolhub tool writes, or signed `toolinfo.json`
  records verified against active local public keys registered in Developer
  settings. Verification is per tool, never global to an author display name or
  Toolhub username.
- **Evolved authorization** (`proxy/backend/authz.py`): Toolhub OAuth remains
  the only sign-in path, while local `users.role` permission sets (`user`,
  `reviewer`, `admin`) gate Evolved-owned data/actions through
  `can(user, action, resource)`. Elevated Evolved roles never bypass official
  Toolhub permissions; `/v1/write/*` still calls Toolhub with the user's own
  OAuth grant and accepts Toolhub's decision before storing any Evolved fallback.
- **Frontend sync** (`lib/core/serversync.js`): real sign-in; localStorage as a
  write-through cache of the server overlay; signed-out write paths are removed
  from the production UI.
- **Crawler** (`proxy/crawl.py` + `jobs.yaml`): hourly ingest of enabled
  registered toolinfo URLs, signed-toolinfo author-claim verification,
  upstream-name de-dupe, create-time `toolinfo_url` enrichment for submitted
  tools, and per-run history.
- **Ops**: nightly DB backup + rotation, `docs/RUNBOOK.md`.
- **i18n**: `t()` catalog mechanism, generated `i18n/en.json` (CI-enforced),
  working locale switcher for shipped catalogs, `pickLocalized()` for API
  fields; chrome strings extracted across views/components. The a11y items
  §2.3 listed as deferred (card grids as lists, crawler table caption/scope)
  were already fixed in code.
- **Project tracking**: GitHub issue #102 is the parent epic for the hybrid
  provenance/write-lifecycle foundation. Child issues #103-#109 track identity,
  provenance, official-first writes, public Evolved-only data controls, UI
  provenance, production data cleanliness, and docs/issue hygiene.

Still open before a public launch: register the Toolhub OAuth application +
ToolsDB and run through the runbook once for real; remove all production-facing
fixtures, mock data, demo writes, deterministic fake metrics, and placeholder
media (tracked by #108); obtain actual translations (the mechanism ships
English-only catalogs); the long-term card-as-link a11y refactor; the
privacy-policy rewrite for server-side accounts and stored OAuth grants (P6).

## 1. Product architecture — "live base + local overlay + official bridge"

The resolved data architecture (§0) is the demonstrator's core insight carried
over unchanged, one level up:

- **The base catalog stays live Toolhub data.** `apiGet` keeps reading
  `toolhub.wikimedia.org` through the same-origin read proxy. We do not fork or
  mirror the upstream catalog; upstream tools always render from live data. The
  read proxy keeps only anonymous, expiring `GET /api/*` payloads in `api_cache`
  so workers share hot responses and can serve short stale data during transient
  upstream failures. The SPA adds a stale-while-revalidate browser cache for the
  same anonymous public reads: stale cached content can render immediately after a
  hard refresh, then a toast announces the live refresh and the route repaints
  when fresh data arrives.
- **Officially supported writes go back to Toolhub.** Toolhub OAuth gives
  Evolved a per-user grant. The browser calls `/v1/write/*`; the backend
  validates locally, checks Evolved policy, attaches the access token, forwards
  to official `/api/*`, and records sync/fallback metadata. Tool creation may
  include a create-only `toolinfo_url`; Evolved fetches it once with the crawler
  safety rules to fill missing optional fields and capture local evidence before
  sending the official Toolhub create.
- **Evolved keeps the additional layer.** Drafts/fallbacks, local overlays,
  local activity rows, and any feature Toolhub does not expose live in our
  database and sync into the browser's localStorage cache.
- **Authorship proof stays Evolved-local.** Verification claims and registered
  public keys help Evolved label "my tools" and provenance, but official Toolhub
  remains authoritative for catalog records and Toolhub permissions. A verified
  author claim is scoped to its exact `tool_name`; the same author name on
  another tool remains unverified until that tool has its own evidence.
- **The merge step is unchanged.** `normalizeTool()`/`normalizeList()` still
  merge an overlay onto the live record at render time; the overlay now comes
  from `GET /v1/…` instead of `localStorage`.

This keeps the product honest by construction: official Toolhub accepts or
rejects canonical writes, while Evolved labels its local overlay as local,
draft, or fallback data instead of presenting it as accepted catalog data.

```
Browser (SPA, public_html/)
  │  GET /api/*   ──────────────►  read proxy ──► api_cache ──► toolhub.wikimedia.org
  │                                                     (anonymous, expiring)   (live, read-only)
  │  GET/POST/PUT/DELETE /v1/overlay/* ─► Evolved API ─► ToolsDB: drafts,
  │                                                        overlays, local state
  │  POST/PUT/DELETE /v1/write/* ───────► Evolved API ─► toolhub.wikimedia.org/api
  │                                      │                 using stored OAuth grant
  │                                      └──────────────► ToolsDB: sync metadata,
  │                                                        fallback rows, activity
  └  GET /oauth/* ─────────────────────► Toolhub OAuth (/o/authorize/, /o/token/)

Toolforge Jobs framework (scheduled)
  └  crawler job ──► fetches registered toolinfo.json URLs ──► validates ──► ToolsDB
```

### Components

| Component     | Choice                                                                                                                                 | Why                                                                                                         |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Web app       | Grow `proxy/app.py` into a small Flask package (blueprints)                                                                            | One Toolforge `python3.13` webservice already serves SPA + proxy; add a `/v1` blueprint, keep the stack     |
| Database      | **ToolsDB (MariaDB)** + SQLAlchemy + Alembic migrations                                                                                | SQLite on Toolforge NFS is unsafe (locking); ToolsDB is the platform-native managed DB                      |
| Auth          | **Toolhub OAuth 2.0** application + server session                                                                                     | Toolhub is the authorization server for Toolhub API writes; `GET /api/user/` maps the official user locally |
| Crawler       | **Toolforge Jobs framework** scheduled job (same repo, `tools/`)                                                                       | Server-side fetch of `toolinfo.json` (schema 1.2.2 validation) — the thing the browser never could          |
| Search        | Phase 1: **federated** (live upstream search + local DB search, merged) · Phase 2: Toolforge shared **Elasticsearch** if quota granted | Local tools become findable immediately without new infra; ES upgrades relevance later                      |
| Static assets | Unchanged (`dist/` build via `tools/deploy.sh`)                                                                                        | Already works                                                                                               |

### The two-catalog question (biggest product risk — decided up front)

The architecture avoids creating a second canonical catalog:

1. **Canonical data is always from Toolhub.** If an official write succeeds,
   the live API becomes the source of truth. If it fails, Evolved can keep a
   local draft/overlay, but it stays labeled as local.
   Single-tool reads always ask live Toolhub first; local new-tool records are
   used only after a real upstream `404`, and local overlays strip canonical
   identity/source fields such as `name` and `origin`.
2. **Local additions are feeder/fallback data, not a fork.** Locally-registered
   tools are exposed as a public **`toolinfo.json` feed** (`/toolinfo.json`) so
   the _official_ Toolhub crawler can ingest them. Toolhub Evolved becomes a
   feeder into the real ecosystem instead of a competing silo.
3. **Upstream courtesy.** Before launch we notify the Toolhub maintainers
   (Phabricator + tool talk page): what the service is, its User-Agent, expected
   API load, and the feed URL. The proxy already identifies itself and caches
   anonymous reads with per-endpoint freshness (`/recent` 30s, search 2min,
   tool/list detail 15min, schema/config 24h) plus 24h stale-if-error; we keep
   respecting the API etiquette. The proxy also polls
   `GET /api/recent/?page_size=50` to track the latest timestamp/id and
   invalidate affected tool, list, recent-feed, and aggregate cache rows; any
   successful official write through Evolved invalidates the same shared cache
   paths immediately.

## 2. What changes in the frontend

Small, because the pivot was designed in:

- **`demoApi` → real API.** The write adapter's mode flag flips: `post/put/delete`
  call `/v1/*`; `localStorage` mutation mode remains available only for tests
  and local development, not production.
- **Mock identity → real session.** The identity picker becomes "Sign in with
  Toolhub"; Toolhub OAuth stores a server-side grant and `GET /v1/user/` drives
  the account menu. Logged-out users get the live read interface, with
  create/update/delete actions prompting Toolhub sign-in.
- **The Evolved layer is part of the default production surface.** Some
  additions are real signed-in write paths through Toolhub OAuth; others are
  local drafts or fallback overlays. The dismissible site notice,
  feature-status page, and _Rules of Engagement_ page explain what is live from
  Toolhub and what is stored in Evolved. Signals and screenshots are shown only
  from real Evolved-owned backend records (`tool_events`, `tool_thanks`,
  `tool_health_*`, `tool_media`) and public local records require Evolved review
  where they affect shared/public pages; there is no synthetic production
  fallback.
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
- Toolhub OAuth 2.0: register the application, `/oauth/login|callback|logout`,
  use `GET /api/user/` to identify the user locally, store the grant server-side,
  session cookie (HttpOnly, Secure, SameSite=Lax), CSRF token for all writes.
- Evolved authorization: local role sets for signed-in users, reviewers, and
  operators; one policy entrypoint (`can(user, action, resource)`); ownership
  checks for private local drafts, overlays, lists, crawler URLs, account data,
  thanks, health targets, and media submissions.
- Cross-cutting: per-user and per-IP rate limits on writes, input validation
  (reuse toolinfo 1.2.2 schema), structured logs, `/healthz`.
- Test story: the proxy tests extend to `/v1` (Flask test client + a throwaway
  MariaDB via container in CI); coverage gates stay at current thresholds.

Exit gate: sign in with Toolhub on Toolforge; session survives restart; a
stored grant can perform a smoke write against official Toolhub; migrations run
via a documented one-liner.

### P2 — First real features: favorites + lists (~1.5 weeks)

- Favorites use `/v1/write/user/favorites/` for official add/delete when
  signed in, with the local overlay as the responsive cache/fallback after an
  authenticated write attempt.
- Lists use `/v1/write/lists/…` for official create/update/delete when
  Toolhub permits it. Evolved draft lists remain local fallback data, rendered
  alongside live upstream lists with provenance labels.
- Evolved-only writes append local `revisions`/`audit_log` rows; official
  Toolhub writes rely on Toolhub's own feeds once accepted.

### P3 — Tool submit / edit / annotations (~2 weeks)

- `POST /v1/write/tools/`, `PUT/DELETE /v1/write/tools/{name}/` — official
  Toolhub remains the permission authority. Core edits are attempted against
  Toolhub; rejected writes become local Evolved drafts/overlays where that is
  honest to display. Create payloads may include `toolinfo_url` for one-shot
  enrichment; Evolved never forwards that field itself to Toolhub.
- `PUT /v1/write/tools/{name}/annotations/` publishes community annotations
  through official Toolhub first, falling back to the Evolved overlay if
  rejected.
- Server-side render-time merge parity: detail pages, cards, and "my
  submissions" show owned records and annotation overlays with provenance
  labels.
- Publish the **`/toolinfo.json` feed** of locally-registered tools (§1.3).

### P4 — Crawler (~1.5 weeks)

- `/v1/write/crawler/urls/` CRUD (auth required) + `Add or remove tools` page
  writes official Toolhub crawler URL registrations when permitted.
- Tool creation can also register a local crawler URL opportunistically through
  its create-only `toolinfo_url` field; that one-shot fetch is for immediate
  enrichment and evidence, while the scheduled job remains the refresh path.
- Toolforge Jobs framework scheduled job (e.g. hourly): fetch each registered
  URL, validate against toolinfo 1.2.2, upsert `tools`, record `crawler_runs`
  with per-URL outcomes; surface runs on the existing `/crawler` history UI.
- Safety: request timeouts, response-size caps (mirror `_MAX_UPSTREAM_BYTES`),
  no redirects to private ranges, per-run URL budget.
- Dedupe by tool name (per the §0 data architecture): if a registered URL
  yields a record that already exists upstream, the live API stays its source
  of truth — we keep at most an overlay, never a shadow copy of upstream data.

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
- **Issue hygiene**: keep #102 as the parent epic, keep child issues linked by
  feature area, and rewrite stale demonstrator wording in open issues before it
  drives implementation work.
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
- Secrets (OAuth client secret, DB URL/credentials, session key): Toolforge
  envvars readable only by the tool, never in the repo; documented in the
  runbook.
- Known platform limits accepted: no custom domain, shared-infra SLAs, ES access
  needs a quota request (hence federated search first).

## 5. Risks

| Risk                                                                   | Mitigation                                                                                                                          |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Catalog divergence from official Toolhub                               | Provenance labeling everywhere + `/toolinfo.json` feeder feed (§1.3) — we add to the ecosystem                                      |
| Upstream API changes/outage breaks the base catalog                    | Already-graceful "couldn't load live data" states; proxy TTL cache absorbs blips; contract tests vs. `/api/schema/` in CI           |
| Community perception (unofficial service using Toolhub data and OAuth) | Early, explicit outreach to maintainers; honest naming; GPL-3.0 code; cached, identified API use; clear write attribution           |
| Solo-maintainer ops burden                                             | Everything scripted and in-repo (deploy, jobs, migrations, backups); external uptime alerting; runbook                              |
| Toolhub OAuth application setup blocks write flows                     | Register the OAuth application before launch; keep read-only mode working when OAuth is unconfigured                                |
| ToolsDB/ES quota limits                                                | Federated-search fallback needs no ES; quota requests early with load estimates                                                     |
| Spam/abuse once writes are real                                        | Wikimedia-account gate, rate limits, Evolved public-data review queue, audit log, admin delete path; new-account throttle if needed |

## 6. Explicit non-goals

- Replacing or upstreaming into the official Toolhub frontend (a separate
  endeavor with a separate process — nothing here precludes it later).
- Custom domain / off-Toolforge hosting (revisit only if Toolforge limits bite).
- Fake usage/health/pageview signals for _upstream_ tools. If real sources are
  not obtainable, those features are dropped from production until they have
  real Evolved-owned backend data.
- Mirroring Toolhub's database or bypassing Toolhub permissions. Official writes
  must always go through Toolhub's API with the user's Toolhub OAuth grant.
