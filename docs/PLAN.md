# Toolhub Evolved — Comprehensive Plan

Last updated: 2026-06-22. Supersedes and merges the three review outputs:
the feature-fix sweep, the i18n/a11y audit (detail kept in
[`AUDIT-i18n-a11y.md`](AUDIT-i18n-a11y.md)), and the standalone-demo research.

## 0. North star and the two lanes

**The interface is frontend-only.** We build and run no application backend. The
only server-side code is the existing thin, read-only CORS shim
(`proxy/app.py`) that forwards `GET /api/*` to `toolhub.wikimedia.org` — that is
not a backend we add features to, it is the reason the browser can read live
catalog data at all.

Every piece of work therefore falls into exactly one of two lanes:

- **Lane A — Shipping interface (default, no flag).** The real, polished
  interface on **live read-only** Toolhub data. Everything here works with the
  read-only API as it exists today: correctness, internationalization,
  accessibility, performance, polish. No backend changes, ever.

- **Lane B — Experiments (behind the existing toggle, real data overloaded with
  fixtures).** Every feature that would require a backend capability the
  read-only API does not give us — any **write**, any **auth/session**, or any
  **signal Toolhub doesn't expose** — lives behind the existing *"Show me
  prospective features"* toggle (`expOn()` / `body.exp-off` / `.experimental`).
  Crucially, **Lane B does not introduce a parallel data source.** It keeps
  reading the same live API as Lane A and **overloads those real records with a
  feature-specific fixture layer** — exactly how `synthViews(name)` already
  decorates a real tool with a synthetic view count. Each feature carries an
  `exp-badge` and a one-line code comment naming the backend capability it would
  need in production.

**The rule that routes all future work:** *if a feature needs a write, a login,
or a number the read-only API doesn't return, it stays in Lane B and is built as
a fixture overlay on top of the real live data — it never replaces the real data
and never blocks or complicates the shipping interface.* Turning the toggle off
strips every overlay and returns the app to a 100% honest, live, read-only
Toolhub experience.

Explicitly **out of scope** (the demo never grows a server): a real write/auth
backend (FastAPI/SQLite/Django), real Wikimedia OAuth, a server-side crawler,
and a real Elasticsearch index. These are recorded in §7 only as "if this is
ever productionized," not as work for this plan.

---

## 1. Baseline — what is already true today

- **Live API data is already wired and stays the substrate everywhere.** The
  vanilla-JS SPA reads **live read-only** data via the read proxy and uses clean
  History API routes; there is no bundled catalog and reads never move to
  fixtures. (Architecture: `main.js`, `views/`, `lib/`, `index.html`, `styles/`,
  `proxy/app.py`.)
- The **experimental toggle already exists** and its synthetic features already
  use the exact pattern this plan generalizes: a **real record overloaded with a
  feature-specific fixture**. `synthViews(name)` decorates a real tool with a
  deterministic view count; reviews, health, usage, and screenshots likewise
  hang off real tools, each behind an `exp-badge` and a
  `// EXPERIMENTAL — MISSING …` comment. **Lane B's mechanism is already in the
  codebase** — every new experiment follows the same overload shape.
- **Lane A correctness is done** (feature-fix sweep, §2.1).
- **Lane A i18n/a11y primitives have landed** (Intl formatters, `lang`/`dir`,
  `<time>`, `dir="auto"`, modal `inert`/focus-trap, `aria-busy`, `aria-current`,
  RTL logical-property CSS). The larger i18n/a11y items remain (§2.2–2.3).

---

## 2. Lane A — Shipping interface (frontend-only, no flag, live read-only data)

### 2.1 Correctness — DONE (baseline quality bar)

The feature-fix sweep found and fixed 7 real defects against the live API. These
define the "no regressions" bar for the shipping interface:

| Sev | Issue | Fix |
| --- | --- | --- |
| High | `/api-docs` iframed a page sending `X-Frame-Options: DENY` (blank frame + console error) | Replaced iframe with doc links + live same-origin endpoint cards |
| Med | "Popular this week" ranked in list order, not by `weeklyViews` | Sort by `weeklyViews` before ranking |
| Med | `/search?sort=views` linked but unsupported (blank select) | Added experimental `views` sort + in-page ranking + exp-off fallback |
| Med | `normalizeTool` ignored annotation-fallback fields (hid real `tool_type`, `for_wikis`, icons, docs, links) | Core-then-annotation fallback |
| Low | "joined **Updated yesterday**" awkward label | Split generic relative-time from update-specific `relTime` (now via `Intl`) |
| Low | Recent-change rows only deep-linked tools | Added list-target routing |
| Low | Audit-log rows showed linkable targets as static text | Added tool/list target routing |

### 2.2 Internationalization (frontend-only)

The catalog data is multilingual but the chrome is English-only. Primitives are
in; the remaining work makes the interface actually localizable. **All
frontend-only — ships in Lane A.** Detail and per-finding locations in
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

### 2.3 Accessibility (frontend-only)

Foundations and the high-value fixes are in (modal isolation, status/`aria-busy`,
`aria-current`, disclosure menu, decorative-icon hiding, RTL). Remaining
deferred items, all frontend-only:

- Card grids exposed as lists (`<ul>`/`<li>` or list semantics) — 1.3.1.
- Crawler table `<caption>` + `scope="col"` — 1.3.1.
- Long-term: tool card as a real link + separate quick-view button — 2.1.1/4.1.2.
- Disambiguate duplicate nav/footer link destinations — 2.4.4.
- Per-field `lang` on API content once language metadata is surfaced — 3.1.2.

Contrast is AA-clean today (one note: star glyphs are decorative; rating is in
text). Effort: ~2–3 days.

### 2.4 Polish & performance (optional, frontend-only)

Response caching of read calls, prefetch on hover, skeleton states, image
lazy-loading audit. Light, opportunistic.

---

## 3. Lane B — Experiments (behind the toggle, live data overloaded with fixtures)

Everything here is gated by `expOn()`. With the toggle **off**, none of it
renders and the app is a pure live read-only catalog. With it **on**, these
features still read the **live API** and overload those real records with a
feature-specific fixture layer (synthetic signals computed per record, and
user-action deltas persisted in browser storage) — no server.

### 3.1 The mechanism — overload live data with feature fixtures (build once, reuse)

Live reads are never replaced. Every experiment fetches the real record through
`apiGet` and then **merges a feature-specific overlay on top at render time.**
There are two overlay kinds:

- **Synthetic-signal overlays — deterministic, no persistence.** A pure function
  of the real record decorates it with a signal the API can't give us:
  `synthViews(name)` (exists), and the same shape for reviews, health, usage, and
  screenshots. Backed by a tiny bundled seed JSON (a **few** sample reviews / demo
  lists / examples — decision §8.7) keyed by tool name for believable content;
  computed/seeded offline, never a runtime data source. These need no store —
  they are recomputed from the live record each render.
- **User-action overlays — persisted in `localStorage`, merged onto the live
  record.** A small **`demoOverlay`** module over **`localStorage`** (decision
  §8.2; namespaced `thdemo:*`) holds only the *delta* the user creates: a set of
  favorited tool **names**, demo lists referencing real tool names, field-level
  **edits layered onto a real tool**, annotation overrides, and net-new
  submissions (a local record shaped like a real tool). At render time the
  overlay is merged over the live read; with the toggle off, the overlay is
  ignored entirely. Ships with a **"Reset demo data"** action.

Supporting pieces:

- **Merge helpers** — extend `normalizeTool()`/`normalizeList()` so a live record
  + its overlay produce one object the existing cards/views render unchanged.
  Favorited/edited state is read by merging the overlay against the live fetch,
  not by querying a separate catalog.
- **Write adapter** — `apiWrite`/`demoApi` (`post`/`put`/`delete`) used *only* by
  flagged features writes into `demoOverlay`; `apiGet` (live reads) is untouched.
  A mode flag keeps the door open for a future real backend without reshaping
  callers.
- **Honest edges** — a submitted/edited tool's overlay shows on its detail page
  and in "my …" views, but it is **not** in live `/api/search/tools/` results
  (that's real and read-only); the UI says so rather than faking search.
- **Labeling contract** — every Lane B feature renders an `exp-badge` and carries
  `// EXPERIMENTAL — Needs: <backend capability> (Toolhub read-only API does not
  expose this)`. The UI must never imply a write touches production Toolhub.

### 3.2 Features (each = a fixture-backed simulation behind the flag)

Reframed from the standalone-demo write catalog; the real endpoints are kept in
Appendix A as the contract each simulation imitates.

| Feature | What the user does (flag on) | Overlay on live data | Needs in production (why it's Lane B) |
| --- | --- | --- | --- |
| **Mock identity** | Explicit "Sign in" identity picker (default *Ada Lovelace*) + "Log out" | session delta in `demoOverlay`; real `/api/users/` data still backs Members | Real Wikimedia OAuth + server session |
| **Favorites** | Save/unsave on cards, quick-view, detail; `/favorites` list | favorited **names** in `demoOverlay`; tool data fetched live and merged | `POST/DELETE /api/user/favorites/` |
| **Lists CRUD** | `/my-lists`, `/lists/create`, `/lists/:id/edit`, delete; reorder tools | demo lists reference real tool names; shown alongside live `/api/lists/` | `POST/PUT/DELETE /api/lists/` |
| **Tool submit / edit** | `/tools/create`, `/tools/:name/edit` (name/title/desc/url + common fields) — editable on **any** tool (decision §8.4, demo-friendly), with core vs. community-annotation fields visually distinguished and an inline note that production limits core edits to `origin="api"` | edits = field overlay merged onto the **live** tool record; new tools = local record shaped like a real one | `POST /api/tools/`, `PUT /api/tools/{name}/` + permissions |
| **Annotations edit** | `/tools/:name/edit-annotations` (audiences, tasks, QID, icon, …) | annotation overrides merged over the live record's `annotations`; detail labels "community" | `PUT /api/tools/{name}/annotations/` |
| **Add / remove tools** | Register a URL; "paste toolinfo JSON" / "load sample" to simulate ingest | local crawler-url + revision/audit deltas merged into the live feeds | Server-side crawler (browser can't fetch arbitrary `toolinfo.json`, CORS) |
| **Developer settings** | **Hidden** (decision §8.5) — route stays a brief "not part of this demo" note | none | Token/OAuth-app backend |
| **History & feeds** | Demo actions append revision/audit rows so `/recent`, `/audit-logs`, history reflect *your* edits | local rows merged on top of the **live** `/api/recent/` & `/api/auditlogs/` feeds | Server write-side-effects |
| **Already-synthetic** (popularity/`weeklyViews`, reviews, health, usage, screenshots) | unchanged; the original overload pattern | deterministic per-tool signal computed from the live record (optional seed JSON) | Real usage/health/review data source |

### 3.3 Route & chrome behavior under the flag

- **The toggle defaults OFF** (decision §8.1). On first visit the app is the pure
  live read-only interface; the user opts into experiments via the existing
  *"Show me prospective features"* switch. The choice persists in `localStorage`.
- The `signInPage()` stubs (`/login`, `/favorites`, `/my-lists`,
  `/lists/create`, `/lists/:id/edit`, `/tools/:name/edit`,
  `/tools/:name/edit-annotations`, `/add-or-remove-tools`) become **real
  flagged views when the toggle is on**, and **keep their current "prospective
  feature" placeholder when off**.
- `/developer-settings` stays **hidden/placeholder in both states** (decision §8.5).
- The header **"Submit a tool"** button: flag on → **in-app `/tools/create`**
  (decision §8.3); flag off → keep the current link to the production create URL.

### 3.4 The mockup banner + "Rules of Engagement" page

These make the live-vs-fixtures distinction impossible to miss whenever
experiments are active.

**Red mockup banner.** While experimental mode is **on**, a persistent red banner
is pinned to the very top of every page (above the header and the `expbar`
toggle strip), shown site-wide — so it is always present on the in-app
submit/edit/favorites pages, which only exist while the toggle is on.

- Copy: *"⚠ Mockup — this is a prototype, not a working integration with the real
  Toolhub. Experimental features are simulated and saved only in your browser."*
  plus a link to **Rules of Engagement**.
- Implementation: a `.mockup-banner` element rendered/visible only when
  `body:not(.exp-off)`; uses the brand destructive (red) token for high contrast;
  `role="region"` with an accessible label; sticky; no animation (reduced-motion
  safe). **Not dismissible** independently of the toggle — the way to remove it is
  to turn experiments off. It is distinct from the `expbar` switch, which stays
  visible in both states so users can flip experiments on/off.

**"Rules of Engagement" page** (`/rules-of-engagement`) — a Lane A prose page
(frontend-only, always reachable), linked from the banner and the footer. It
explains the model in plain language:

- **What this is** — a design prototype on a separate domain, not production Toolhub.
- **What's real** — the catalog, search/facets, tool detail, lists, members,
  recent changes, crawler history, audit logs: all **live, read-only** from
  `toolhub.wikimedia.org` through a read-only proxy.
- **What's simulated** (experiments) — sign-in, favorites, list create/edit, tool
  submit/edit, annotations, and synthetic signals (popularity, reviews, health,
  usage, screenshots). These **overload the real records with fixtures/local
  overlays**.
- **Where your actions go** — stored only in this browser (`localStorage`),
  per-browser, **never sent to Toolhub**; "Reset demo data" clears them; turning
  the toggle off strips every overlay.
- **Honest edges** — a demo-created or demo-edited tool will not appear in live
  search, because search is real and read-only.

---

## 4. Frontend code shape (no backend)

- Keep `apiGet(path, params)` for live reads — unchanged; it stays the only data
  source for the base records.
- Add `demoOverlay` (a thin `localStorage` wrapper for user-action deltas) and
  `apiWrite`/`demoApi` (`post/put/delete`) used **only** inside `expOn()`
  branches; writes land in `demoOverlay`, never on the network.
- Default the toggle **off** (flip the current `EXP_KEY` default) and render the
  `.mockup-banner` whenever `expOn()`; both the banner and the
  `/rules-of-engagement` page are wired in the same change.
- Add a thin **merge step**: after `normalizeTool()`/`normalizeList()` produce the
  live object, when `expOn()` apply the matching overlay (favorite flag, field
  edits, annotation overrides, synthetic signals) so the existing cards/views
  render the decorated object unchanged. When the toggle is off, the merge is a
  no-op and only live data shows.
- Gate every Lane B view/control behind `expOn()`; rely on the existing
  `body.exp-off` / `.experimental` hiding so toggling is instant and complete.
- One golden rule in review: **no Lane B code path runs and no overlay is merged
  when the toggle is off** — the app is then byte-for-byte the live read-only
  interface.

---

## 5. Phases & effort (all frontend)

| Phase | Lane | Work | Effort |
| --- | --- | --- | --- |
| P0 | — | Lock this plan + the overlay contract (decisions §8 resolved below) | 0.5 d |
| P1 | A | i18n catalog + `t()` (audit phases 1–2) and the deferred a11y items | 4–6 d |
| P2 | B | **Toggle default-off + red mockup banner + `/rules-of-engagement` page**, then `demoOverlay` (`localStorage`) + the live-record merge step + mock identity + favorites | 3–4 d |
| P3 | B | Lists CRUD (`my-lists`, create/edit/delete, reorder) | 2–3 d |
| P4 | B | Tool submit/edit (editable on any tool, core/annotation labeled) + annotations edit + local revision/audit side-effects | 3–4 d |
| P5 | B | Add/remove-tools simulation (paste/sample JSON); keep dev-settings hidden | 1.5–2 d |
| P6 | B | Unify existing synthetic features under the same overload pattern; add the per-feature "Needs:" comments | 1–2 d |
| P7 | A | i18n phases 3–5 (prose, localized fields, language switcher) + polish | 3–5 d |

Total: **~3 weeks**, entirely frontend. Lanes A and B are independent — i18n/a11y
can ship while Lane B is still in progress, and vice versa.

---

## 6. Risks (frontend-only framing)

- **State is per-browser.** No shared state between visitors — intended and
  acceptable for a flagged demo; surface it in copy ("saved only in this
  browser").
- **Submitted/edited tools aren't in live search.** By design — shown only in
  "my submissions"/overlay views, clearly labeled.
- **Synthetic signals must stay labeled.** This is exactly what the toggle is
  for; never let a Lane B value read as live Toolhub data.
- **Fixture/seed staleness.** Show seed provenance/date where seed data backs a
  feature.
- **Crawler fidelity.** The browser can't fetch arbitrary `toolinfo.json` (CORS),
  so ingestion is simulated via paste/sample — documented, not hidden.

---

## 7. Out of scope (only if ever productionized)

Recorded so the boundary is explicit; **not** work for this plan: a real
write/auth backend (FastAPI/SQLite/Django), real Wikimedia OAuth (separate
registered app + callback), a server-side crawler that fetches `toolinfo.json`,
and a real Elasticsearch index for production-grade relevance. The Lane B write
adapter is intentionally shaped like Toolhub's real endpoints (Appendix A) so
that, if this day ever comes, callers don't change — only the adapter's target.

---

## 8. Decisions — RESOLVED (2026-06-22)

1. **Default toggle state → OFF.** First visit is the pure live read-only
   interface; users opt into experiments. Choice persists in `localStorage`.
2. **Storage → `localStorage`** for all demo-write overlays (`demoOverlay`).
3. **"Submit a tool" with flag on → in-app form** (`/tools/create`), with the
   red mockup banner present (§3.4). Flag off → keep the external production link.
4. **Crawler-origin tools in the edit experiment → demo-friendly.** Editable on
   any tool via overlay, with core vs. community-annotation fields visually
   distinguished and an inline note that production limits core edits to
   `origin="api"`. (Recommendation; flip to faithful/annotation-only on request.)
5. **Developer settings → hidden.** The route keeps a brief "not part of this
   demo" note in both states.
6. **Synthetic features (reviews/health/popularity/screenshots) → keep as
   fixtures**, unified under the overload pattern.
7. **Seed scope → small.** A few sample reviews and a few demo lists/examples —
   just enough to make the experiments believable.

Always-on labeling (from these decisions): the **red mockup banner** shows on
every page whenever experiments are on, and links to the **Rules of Engagement**
page (§3.4) explaining live data vs. fixtures.

---

## Appendix A — Toolhub endpoint/field reference (the contract Lane B imitates)

Kept so each fixture-backed simulation matches real Toolhub shapes (researched
2026-06-22 against `/api/`, `/api/schema/`, the toolinfo `1.2.2` schema, and the
source tree).

**Read endpoints the shipping interface uses (live):** `GET /api/ui/home/`,
`GET /api/search/tools/` (`q`, `page`, `page_size`, `ordering`, `*__term` facets
→ `count/next/previous/results/facets`), `GET /api/tools/{name}/`,
`GET /api/tools/{name}/revisions/`, `GET /api/lists/` (+`?featured=true`),
`GET /api/lists/{id}/`, `GET /api/recent/`, `GET /api/users/`,
`GET /api/crawler/runs/`, `GET /api/auditlogs/`.

**Write/auth endpoints each Lane B feature imitates (simulated, never called for real):**
`GET /api/user/` (+ demo login/logout); `GET/POST /api/user/favorites/`,
`DELETE /api/user/favorites/{tool_name}/`; `POST /api/tools/`,
`PUT /api/tools/{name}/`; `GET/PUT /api/tools/{name}/annotations/`;
`POST /api/lists/`, `PUT/DELETE /api/lists/{id}/`, `GET /api/lists/{id}/revisions/`;
`GET/POST /api/crawler/urls/`, `DELETE /api/crawler/urls/{id}/`;
`GET/POST/DELETE /api/user/authtoken/`.

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
