# Toolhub Evolved — Comprehensive Plan

Last updated: 2026-07-27. Supersedes and merges the three review outputs:
the feature-fix sweep, the i18n/a11y audit (detail kept in
[`AUDIT-i18n-a11y.md`](AUDIT-i18n-a11y.md)), and the standalone-demo research.

## 0. North star and the two lanes

**The interface is a Toolhub-canonical hybrid.** Evolved reads live Toolhub data
through its backend cache/proxy, writes to official Toolhub first when the API
supports the action, and stores only Evolved-specific overlays, fallback drafts,
verification evidence, moderation state, and cache rows in its local database.

Every piece of work therefore falls into exactly one of two lanes:

- **Lane A — Official Toolhub substrate.** The polished interface on **live**
  Toolhub data. Everything here preserves Toolhub as canonical: correctness,
  internationalization, accessibility, performance, and careful cache behavior.

- **Lane B — Hybrid Evolved layer (default-on, real data plus labeled local
  overlays).** Features that require a backend capability beyond the official
  read API — any **write**, any **auth/session**, or any **signal Toolhub
  doesn't expose** — now live in the production Evolved layer. Crucially, this
  layer does not replace Toolhub as the base data source: it keeps reading the
  same live API and layers clearly labeled local Evolved records on top.

**The rule that routes all future work:** _if a feature needs a write, a login,
or a number the official API doesn't return, it belongs in the hybrid Evolved
layer and must stay clearly labeled — it never replaces the real Toolhub base
data._

Explicitly **out of scope**: replacing official Toolhub as the canonical catalog,
granting Toolhub admin meaning to Evolved-local roles, global author verification
by display name, and broad public writes before moderation/abuse controls exist.

---

## 1. Baseline — what is already true today

- **Live API data is already wired and stays the substrate everywhere.** The
  vanilla-JS SPA reads live data via the backend proxy/cache and uses clean
  History API routes; there is no bundled catalog and reads never move to
  production fixtures. (Architecture: `main.js`, `views/`, `lib/`, `index.html`,
  `styles/`, `proxy/backend/`, `proxy/app.py`.)
- The previous **experimental-toggle surface** has been removed. Evolved
  additions are now default-visible production features, with provenance and
  sync-status labels replacing the old opt-in switch.
- **Lane A correctness is done** (feature-fix sweep, §2.1).
- **Lane A i18n/a11y primitives have landed** (Intl formatters, `lang`/`dir`,
  `<time>`, `dir="auto"`, modal `inert`/focus-trap, `aria-busy`, `aria-current`,
  RTL logical-property CSS). The larger i18n/a11y items remain (§2.2–2.3).

---

## 2. Lane A — Shipping interface (live Toolhub data, no feature flag)

### 2.1 Correctness — DONE (baseline quality bar)

The feature-fix sweep found and fixed 7 real defects against the live API. These
define the "no regressions" bar for the shipping interface:

| Sev  | Issue                                                                                                      | Fix                                                                         |
| ---- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| High | `/api-docs` iframed a page sending `X-Frame-Options: DENY` (blank frame + console error)                   | Replaced iframe with doc links + live same-origin endpoint cards            |
| Med  | Obsolete popularity sort used synthetic `weeklyViews`                                                      | Removed from production UI until backed by real Evolved data                |
| Med  | `/search?sort=views` linked but unsupported (blank select)                                                 | Stale requests now fall back to the production relevance sort               |
| Med  | `normalizeTool` ignored annotation-fallback fields (hid real `tool_type`, `for_wikis`, icons, docs, links) | Core-then-annotation fallback                                               |
| Low  | "joined **Updated yesterday**" awkward label                                                               | Split generic relative-time from update-specific `relTime` (now via `Intl`) |
| Low  | Recent-change rows only deep-linked tools                                                                  | Added list-target routing                                                   |
| Low  | Audit-log rows showed linkable targets as static text                                                      | Added tool/list target routing                                              |

### 2.2 Internationalization

The catalog data is multilingual but the chrome is English-only. Primitives are
in; the remaining work makes the interface actually localizable. **All
mostly frontend — ships in Lane A.** Detail and per-finding locations in
[`AUDIT-i18n-a11y.md`](AUDIT-i18n-a11y.md).

No-build architecture (already chosen): plain JSON catalogs + a tiny
`t(key, params)` over `Intl.*`; `setLocale()` writes `toolhub-locale`, sets
`lang`/`dir`, reloads messages, re-renders the route. Translatewiki-compatible
keys. Never concatenate translated fragments; API data stays data with
`dir="auto"` + `lang` when known.

Phased (from the audit):

1. Move shell/nav/footer/account/search/card strings to `i18n/en.json` + `t()`.
2. Move detail, quick-view, list, and parity-page strings.
3. Move static prose pages to per-locale fragments.
4. Localized field selection for Toolhub API data (prefer active locale → language fallback → default).
5. Visible language switcher + pseudolocalization + RTL smoke page in local QA.

Effort: ~4–7 days across phases 1–5.

### 2.3 Accessibility

Foundations and the high-value fixes are in (modal isolation, status/`aria-busy`,
`aria-current`, disclosure menu, decorative-icon hiding, RTL). Remaining
deferred items:

- Card grids exposed as lists (`<ul>`/`<li>` or list semantics) — 1.3.1.
- Crawler table `<caption>` + `scope="col"` — 1.3.1.
- Long-term: tool card as a real link + separate quick-view button — 2.1.1/4.1.2.
- Disambiguate duplicate nav/footer link destinations — 2.4.4.
- Per-field `lang` on API content once language metadata is surfaced — 3.1.2.

Contrast is AA-clean today (one note: star glyphs are decorative; rating is in
text). Effort: ~2–3 days.

### 2.4 Polish & performance

Response caching of read calls, prefetch on hover, skeleton states, image
lazy-loading audit. Light, opportunistic.

---

## 3. Lane B — Hybrid Evolved Layer (default-on, labeled local data)

Everything here now renders by default when relevant. These features still read
the **live API** as the base and layer clearly labeled Evolved-local data on top
through the backend overlay API — no synthetic production fixtures.

### 3.1 The mechanism — live Toolhub base + Evolved backend overlays

Live reads are never replaced. The browser fetches through the Evolved backend,
which uses live Toolhub API responses as the base, applies endpoint-aware shared
cache rules, and merges clearly labeled Evolved-local records where the feature
requires data Toolhub does not expose.

There are two overlay kinds:

- **Official-first user data.** Favorites, lists, tool writes, annotations, and
  crawler URL registration validate locally, check Evolved permissions, attempt
  the official Toolhub API when supported, then record sync metadata and
  fallback/draft state in the local database when Toolhub rejects a write.
- **Evolved-only data.** Health, thanks, media, local tool rows, crawler run
  evidence, and per-tool author verification are stored in local backend tables,
  protected by Evolved permissions, and labeled as Evolved data. Public
  Evolved-owned data needs review/moderation before broad exposure.

Supporting pieces:

- **Merge helpers** — extend `normalizeTool()`/`normalizeList()` so a live
  record plus its Evolved overlay produce one object the existing cards/views
  render unchanged. Favorited/edited state is read by merging the overlay against
  the live fetch, not by querying a separate catalog.
- **Write adapter** — `serverWrite()` targets `/v1/write/*` and related overlay
  endpoints. The backend owns the official-first lifecycle, fallback state,
  structured activity, and retry/discard paths.
- **Honest edges** — a submitted/edited tool only becomes canonical when Toolhub
  accepts it. Rejected writes remain Evolved-local drafts/fallbacks with
  visible sync status.
- **Labeling contract** — every field or action that mixes provenance exposes
  whether it is published to Toolhub, saved locally, saved locally after Toolhub
  rejected it, pending review, retryable, or discardable.

### 3.2 Features

| Feature                         | What the user does                                                                                                                     | Hybrid data contract                                                                                                                              | Backend dependency                                        |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| **Toolhub OAuth identity**      | Sign in with Toolhub and let Evolved identify the local user via `/api/user/`.                                                         | Toolhub OAuth is the only sign-in; local users/roles derive from that identity.                                                                   | OAuth session + CSRF + `/v1/user/`                        |
| **Favorites**                   | Save/unsave on cards, quick-view, detail; review `/favorites`.                                                                         | Official Toolhub write first where available; local fallback remains private to the signed-in user.                                               | `/v1/write/favorites/`                                    |
| **Lists CRUD**                  | `/my-lists`, `/lists/create`, `/lists/:id/edit`, delete; reorder tools.                                                                | Official list writes first; local fallback records retain ownership, sync status, retry, and discard paths.                                       | `/v1/write/lists/`                                        |
| **Tool submit / edit**          | `/tools/create`, `/tools/:name/edit` with provenance and sync-status controls.                                                         | Official Toolhub is canonical; Evolved stores local drafts/fallbacks and create-time `toolinfo_url` enrichment evidence.                          | `/v1/write/tools/` + crawler                              |
| **Annotations edit**            | `/tools/:name/edit-annotations` for community-facing metadata.                                                                         | Official annotation write first; rejected annotations remain Evolved-local overlays.                                                              | `/v1/write/tools/:name/annotations/`                      |
| **Developer settings**          | Manage official Toolhub developer links, local signed-toolinfo public keys, and signing payload helpers.                               | OAuth apps/API tokens remain official Toolhub data; public keys and signed-toolinfo verification are Evolved-local.                               | `/v1/author-keys/`, `/v1/toolinfo/signing-payload/`       |
| **My tools**                    | Review official Toolhub tools associated with the signed-in user, paste homepage/toolinfo URLs, and manage local toolinfo submissions. | Tool rows come from official Toolhub; per-tool evidence, official feed sources, root/sitemap discovery, and local ingestion remain Evolved-local. | `/v1/me/tools/` + author claims + source caches + crawler |
| **History & feeds**             | Browse `/recent` and see official Toolhub activity merged with Evolved-local write activity.                                           | Official recent changes stay primary; local writes append structured activity with provenance.                                                    | `/v1/recent/` + shared API cache                          |
| **Evolved-only public signals** | View health, thanks, media, screenshots, and similar data once reviewed/available.                                                     | Stored locally, permission-checked, moderated where public, and labeled as Evolved data.                                                          | local overlay tables + moderation                         |

### 3.3 Route & chrome behavior

- **Evolved features are default-visible.** The legacy feature toggle has been
  removed; users no longer need to opt in before using the hybrid flows.
- The `signInPage()` stubs (`/login`, `/favorites`, `/my-lists`,
  `/lists/create`, `/lists/:id/edit`, `/tools/:name/edit`,
  `/tools/:name/edit-annotations`, `/my-tools`) become **real hybrid
  views** backed by official-first writes and Evolved-local fallback storage.
- The header **"Submit a tool"** button uses the in-app `/tools/create` hybrid
  flow.

### 3.4 The site notice + "Rules of Engagement" page

These make the live-vs-Evolved distinction clear without blocking normal use.

**Site notice.** A persistent red notice is shown at the very top of every page
by default, so the hybrid state is visible on in-app submit/edit/favorites pages.

- Copy: _"Evolved preview: live Toolhub data with Evolved additions."_ plus links
  to **Feature status** and **Rules of Engagement**.
- Implementation: a compact `.mockup-banner` element visible by default;
  `role="region"` with an accessible label; no animation (reduced-motion safe).
  A small dismiss button stores `toolhub-sitenotice-dismissed=1` in
  `localStorage` so future sessions keep it hidden.

**"Rules of Engagement" page** (`/rules-of-engagement`) — a Lane A prose page
(frontend-only, always reachable), linked from the banner and the footer. It
explains the model in plain language:

- **What this is** — a design prototype on a separate domain, not production Toolhub.
- **What's real** — the catalog, search/facets, tool detail, lists, members,
  recent changes, crawler history, audit logs: all **live, read-only** from
  `toolhub.wikimedia.org` through a read-only proxy.
- **What's Evolved-local** — fallback writes, local drafts, review queues,
  Evolved-only signals, crawler evidence, and signed-toolinfo verification.
- **Where your actions go** — official-first writes go to Toolhub when accepted;
  rejected or draft data is stored in Evolved-local backend tables with clear
  provenance.
- **Honest edges** — a demo-created or demo-edited tool will not appear in live
  search, because search is real and read-only.

---

## 4. Frontend/backend code shape

- Keep `apiGet(path, params)` for live reads — unchanged; it stays the only data
  source for the base records, now routed through backend cache/proxy paths where
  needed for resilience.
- Add backend overlay storage for user-action deltas and official-first write
  adapters; local storage remains a cache/test fallback, not production source
  of truth.
- Render the `.mockup-banner` by default; its dismiss button persists only the
  site-notice preference in `localStorage`.
- Add a thin **merge step**: after `normalizeTool()`/`normalizeList()` produce the
  live object, apply the matching Evolved overlay (favorite flag, field edits,
  annotation overrides, real Evolved-owned signals) so existing cards/views
  render the decorated object unchanged.
- Gate no production view behind an Evolved feature toggle; use provenance labels
  and sync-status copy instead.

---

## 5. Foundation Status

- **Shipped:** Toolhub OAuth sign-in, local user mapping, Evolved role/policy
  entrypoint, official-first write lifecycle, local fallback records, shared
  provenance fields, retry/discard controls, feature-status docs, and compact
  dismissible site notice.
- **Shipped:** Developer settings now link to official Toolhub OAuth/app/token
  pages and expose Evolved-local signed-toolinfo public-key management.
- **Shipped:** `/my-tools` resolves tools from the signed-in Toolhub username and
  Toolforge `tools.*` memberships, then displays per-tool verification badges
  for Toolforge maintainer, Toolhub write access, signed toolinfo, and
  unverified author-name matches.
- **Shipped:** Tool creation accepts a create-only `toolinfo_url`; Evolved fetches
  it immediately to fill missing fields and register crawler/signed-toolinfo
  evidence, while official Toolhub remains canonical.
- **Current follow-up work:** expand Evolved-only public signals beyond the
  foundation tables, add moderation workflows per surface, and remove any
  remaining non-production fixture paths before broad public writes.

The older frontend-only demo phases are superseded by
`docs/HYBRID-FEATURE-PLAN.md`, `docs/PRODUCTION.md`, and `docs/RUNBOOK.md`.

---

## 6. Risks

- **Canonical-source confusion.** Toolhub remains authoritative for official
  catalog records; Evolved-local fallback, verification, health, thanks, and
  media data must stay visibly labeled.
- **Authorship false positives.** Author display names are not unique. Only
  per-tool Toolforge maintainer, Toolhub write-access, or signed-toolinfo
  evidence may mark a claim verified.
- **Fallback visibility.** Submitted/edited data may remain local when Toolhub
  rejects it; the UI must keep retry/discard and sync-error states clear.
- **Evolved-only signals must stay labeled.** Never let an Evolved-local value
  read as live Toolhub data.
- **Crawler trust.** Browser CORS no longer blocks ingestion because the backend
  fetches `toolinfo.json`; crawler inputs still require public-HTTPS validation,
  owner checks, and signed-toolinfo verification where used.

---

## 7. Out of scope / Deferred

- Replacing official Toolhub as the canonical catalog.
- Treating Evolved-local roles as Toolhub admin rights.
- Global author verification by display name.
- Full production-grade search indexing independent of Toolhub.
- Broad public Evolved-only writes before review, moderation, ownership checks,
  and abuse controls are in place for that surface.

---

## 8. Decisions — Current

1. **Evolved feature toggle → removed.** Hybrid Evolved features are
   default-visible; only the site notice dismissal persists in `localStorage`.
2. **Storage → backend database** for local overlays, provenance, crawler URLs,
   author claims, public-key records, sync metadata, moderation state, and shared
   anonymous Toolhub API cache.
3. **"Submit a tool" → in-app official-first form** (`/tools/create`) with
   optional create-time `toolinfo_url` enrichment.
4. **Crawler-origin data → maintainer-owned.** The backend fetches registered
   `toolinfo.json` URLs and records evidence; core official Toolhub writes still
   follow Toolhub permissions and origin rules.
5. **Developer settings → shipped.** The page exposes official Toolhub links and
   Evolved-local signed-toolinfo key/payload tooling.
6. **Fixtures/mock data → production cleanup target.** Any remaining fixture
   paths are treated as test-only or pending removal, not production content.
7. **Author verification → per tool only.** Verified evidence for one tool never
   verifies the same author display name on another tool.

Always-on labeling (from these decisions): the compact site notice shows on
every page by default, can be dismissed locally, and links to **Feature status**
and **Rules of Engagement** explaining live Toolhub data vs. Evolved-local data.

---

## Appendix A — Toolhub endpoint/field reference (the contract Lane B imitates)

Kept so each hybrid feature matches real Toolhub shapes (researched
2026-06-22 against `/api/`, `/api/schema/`, the toolinfo `1.2.2` schema, and the
source tree).

**Read endpoints the shipping interface uses (live):** `GET /api/ui/home/`,
`GET /api/search/tools/` (`q`, `page`, `page_size`, `ordering`, `*__term` facets
→ `count/next/previous/results/facets`), `GET /api/tools/{name}/`,
`GET /api/tools/{name}/revisions/`, `GET /api/lists/` (+`?featured=true`),
`GET /api/lists/{id}/`, `GET /api/recent/`, `GET /api/users/`,
`GET /api/crawler/runs/`, `GET /api/auditlogs/`.

**Official-first and Evolved-local write/auth paths:** `GET /api/user/` through
Toolhub OAuth-backed session identity; `/v1/write/favorites/`;
`/v1/write/lists/`; `/v1/write/tools/`; `/v1/write/tools/{name}/`;
`/v1/write/tools/{name}/annotations/`; `/v1/crawler/urls/`;
`/v1/me/tools/`; `/v1/author-keys/`; `/v1/toolinfo/signing-payload/`.
The backend decides whether the operation can be sent to official Toolhub,
records sync metadata, and keeps any allowed fallback/draft data local to
Evolved.

**Tool shape:** core fields (`name`, `title`, `description`, `url`, `keywords`,
`author`, `repository`, `deprecated`, `experimental`, `for_wikis`, `icon`,
`license`, `available_ui_languages`, `technology_used`, `tool_type`, `api_url`,
docs/feedback/bug/translate URLs, `origin`, `created_by/date`,
`modified_by/date`) **plus** a separate `annotations` object (`wikidata_qid`,
`audiences`, `content_types`, `tasks`, `subject_domains`, and overridable common
fields). Required for create: `name`, `title`, `description`, `url`. Toolhub's
real permission rule (worth imitating in the edit experiment): only
`origin="api"` records are core-editable; crawler-origin records are updated via
annotations.

## Appendix B — i18n / a11y detail

Full prioritized findings, WCAG criteria, locations, and contrast ratios live in
[`AUDIT-i18n-a11y.md`](AUDIT-i18n-a11y.md).
