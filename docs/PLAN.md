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

- **Lane B — Experiments (behind the existing toggle, fixtures only).** Every
  feature that would require a backend capability the read-only API does not
  give us — any **write**, any **auth/session**, or any **signal Toolhub doesn't
  expose** — lives behind the existing *"Show me prospective features"* toggle
  (`expOn()` / `body.exp-off` / `.experimental`). It is faked with **fixtures**:
  bundled seed JSON for believable content, plus `localStorage`/`IndexedDB` for
  user-generated demo state. Each carries an `exp-badge` and a one-line code
  comment naming the backend capability it would need in production.

**The rule that routes all future work:** *if a feature needs a write, a login,
or a number the read-only API doesn't return, it goes in Lane B with fixtures —
it never blocks or complicates the shipping interface.* Turning the toggle off
returns the app to a 100% honest, live, read-only Toolhub experience.

Explicitly **out of scope** (the demo never grows a server): a real write/auth
backend (FastAPI/SQLite/Django), real Wikimedia OAuth, a server-side crawler,
and a real Elasticsearch index. These are recorded in §7 only as "if this is
ever productionized," not as work for this plan.

---

## 1. Baseline — what is already true today

- Vanilla-JS hash-routed SPA reading **live read-only** data via the read proxy;
  no bundled catalog. (Architecture: `app.js`, `index.html`, `styles.css`,
  `tokens.css`, `proxy/app.py`.)
- The **experimental toggle already exists** and already gates synthetic
  features (popularity/`weeklyViews`, reviews, health, usage, screenshots) with
  `exp-badge`s and `// EXPERIMENTAL — MISSING …` code comments. **Lane B's
  mechanism is already in the codebase** — this plan generalizes it.
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
| High | `#/api-docs` iframed a page sending `X-Frame-Options: DENY` (blank frame + console error) | Replaced iframe with doc links + live same-origin endpoint cards |
| Med | "Popular this week" ranked in list order, not by `weeklyViews` | Sort by `weeklyViews` before ranking |
| Med | `#/search?sort=views` linked but unsupported (blank select) | Added experimental `views` sort + in-page ranking + exp-off fallback |
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

## 3. Lane B — Experiments (behind the toggle, fixtures only)

Everything here is gated by `expOn()`. With the toggle **off**, none of it
renders and the app is a pure live read-only catalog. With it **on**, these
features work end-to-end against **fixtures + browser storage** — no server.

### 3.1 The mechanism (build once, reuse for every feature)

- **`demoStore`** — a small module over `localStorage`/`IndexedDB`, namespaced
  `thdemo:*`, holding all user-generated demo state (session, favorites, lists,
  submitted/edited tools, annotations). Ships with a **"Reset demo data"**
  action.
- **Seed fixtures** — small bundled JSON for believable synthetic content
  (sample reviews, usage seeds, a sample `toolinfo.json`, a couple of demo
  lists). Tiny; generated offline (optional `tools/seed-*.mjs`), never fetched at
  runtime.
- **Reads stay live.** Favorites/lists store **tool names**; the tool data is
  fetched live. A submitted/edited tool lives only as a local overlay, shown in
  "my …" views — it is honestly **not** in live search.
- **Write adapter** — add `apiWrite`/`demoApi` (`post`/`put`/`delete`) used
  *only* by flagged features; `apiGet` (live reads) is untouched. A mode flag
  keeps the door open for a future real backend without reshaping callers.
- **Labeling contract** — every Lane B feature renders an `exp-badge` and
  carries `// EXPERIMENTAL — Needs: <backend capability> (Toolhub read-only API
  does not expose this)`. The UI must never imply a write touches production
  Toolhub.

### 3.2 Features (each = a fixture-backed simulation behind the flag)

Reframed from the standalone-demo write catalog; the real endpoints are kept in
Appendix A as the contract each simulation imitates.

| Feature | What the user does (flag on) | Fixture/store model | Needs in production (why it's Lane B) |
| --- | --- | --- | --- |
| **Mock identity** | Explicit "Sign in" identity picker (default *Schiste*) + "Log out" | session record in `demoStore` | Real Wikimedia OAuth + server session |
| **Favorites** | Save/unsave on cards, quick-view, detail; `#/favorites` list | set of tool names in `demoStore` | `POST/DELETE /api/user/favorites/` |
| **Lists CRUD** | `#/my-lists`, `#/lists/create`, `#/lists/:id/edit`, delete; reorder tools | list rows + ordered names in `demoStore` | `POST/PUT/DELETE /api/lists/` |
| **Tool submit / edit** | `#/tools/create`, `#/tools/:name/edit` (name/title/desc/url + common fields) | local overlay tool, `origin="api"` | `POST /api/tools/`, `PUT /api/tools/{name}/` + permissions |
| **Annotations edit** | `#/tools/:name/edit-annotations` (audiences, tasks, QID, icon, …) | annotation row in `demoStore`; detail merges + labels "community" | `PUT /api/tools/{name}/annotations/` |
| **Add / remove tools** | Register a URL; "paste toolinfo JSON" / "load sample" to simulate ingest | local crawler-url + revision/audit rows | Server-side crawler (browser can't fetch arbitrary `toolinfo.json`, CORS) |
| **Developer settings** | Local-only demo API tokens (or hidden) | token rows in `demoStore` | Token/OAuth-app backend |
| **History & feeds become live** | Local writes create revision/audit rows so `#/recent`, `#/audit-logs`, history stop being decorative *for demo actions* | append to `demoStore` feeds, merged with live reads | Server write-side-effects |
| **Already-synthetic** (popularity/`weeklyViews`, reviews, health, usage, screenshots) | unchanged; now unified under the same fixtures mechanism | seed fixtures, deterministic per tool | Real usage/health/review data source |

### 3.3 Route & chrome behavior under the flag

- The `signInPage()` stubs (`#/login`, `#/favorites`, `#/my-lists`,
  `#/lists/create`, `#/lists/:id/edit`, `#/tools/:name/edit`,
  `#/tools/:name/edit-annotations`, `#/add-or-remove-tools`,
  `#/developer-settings`) become **real flagged views when the toggle is on**,
  and **keep their current "prospective feature" placeholder when off**.
- The header **"Submit a tool"** button: flag on → in-app `#/tools/create`; flag
  off → keep the current link to the production create URL.

---

## 4. Frontend code shape (no backend)

- Keep `apiGet(path, params)` for live reads — unchanged.
- Add `demoStore` (browser storage) and `demoApi`/`apiWrite` (`post/put/delete`)
  used **only** inside `expOn()` branches.
- Gate every Lane B view/control behind `expOn()`; rely on the existing
  `body.exp-off` / `.experimental` hiding so toggling is instant and complete.
- Keep `normalizeTool()`/`normalizeList()`; Lane B overlays reuse them so a
  demo-created tool renders through the same cards.
- One golden rule in review: **no Lane B code path runs when the toggle is off.**

---

## 5. Phases & effort (all frontend)

| Phase | Lane | Work | Effort |
| --- | --- | --- | --- |
| P0 | — | Lock this plan + the fixture/store contract; pick decisions in §8 | 0.5 d |
| P1 | A | i18n catalog + `t()` (audit phases 1–2) and the deferred a11y items | 4–6 d |
| P2 | B | `demoStore` + seed fixtures + mock identity + favorites | 2–3 d |
| P3 | B | Lists CRUD (`my-lists`, create/edit/delete, reorder) | 2–3 d |
| P4 | B | Tool submit/edit + annotations edit + local revision/audit side-effects | 3–4 d |
| P5 | B | Add/remove-tools simulation (paste/sample JSON) + dev-settings decision | 1.5–2 d |
| P6 | B | Unify existing synthetic features under the fixtures mechanism; add the per-feature "Needs:" comments | 1–2 d |
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

## 8. Decisions for you

1. **Default toggle state** — keep prospective features **on** by default (current),
   or default **off** for a clean, fully-honest first impression?
2. **Storage** — `localStorage` (simplest) or `IndexedDB` (more room, async) for demo writes?
3. **"Submit a tool" with flag on** — in-app flagged form, or keep the external production link even when experimenting?
4. **Snapshot `origin="crawler"` tools** — in the edit experiment, faithful (annotation-only) or demo-friendly ("copy into an editable demo record")?
5. **Developer settings** — implement local demo tokens, or hide the route until/unless useful?
6. **Synthetic features** (reviews/health/popularity/screenshots) — keep as fixture-backed demo data, or trim any you don't want to show?
7. **Seed scope** — how much sample content to bundle (e.g. N sample reviews, a few demo lists)?

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
