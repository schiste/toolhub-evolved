# Toolhub Evolved i18n and a11y audit

Date: 2026-06-22

Scope: `public_html/index.html`, `public_html/app.js`, `public_html/styles.css`, and `public_html/tokens.css`. The proxy was only used to run the app and was not audited for UI strings.

Severity summary:

| Area | Critical | High | Medium | Low | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| i18n | 0 | 4 | 6 | 2 | 12 |
| a11y | 0 | 3 | 7 | 4 | 14 |
| Total | 0 | 7 | 13 | 6 | 26 |

Hardcoded user-facing string inventory:

| Surface | Count | Representative locations |
| --- | ---: | --- |
| HTML shell chrome | 46 | `public_html/index.html:7`, `public_html/index.html:17`, `public_html/index.html:25-32`, `public_html/index.html:42-45`, `public_html/index.html:55-97`, `public_html/index.html:104` |
| JS chrome, views, cards, account, route titles, live-data labels | 254 | `public_html/app.js:139`, `public_html/app.js:164`, `public_html/app.js:180-208`, `public_html/app.js:221-294`, `public_html/app.js:313-409`, `public_html/app.js:414-548`, `public_html/app.js:697-737`, `public_html/app.js:740-875`, `public_html/app.js:963-1059` |
| JS static prose pages | 92 | `public_html/app.js:577-690` |
| Total message occurrences | 392 | Excludes selectors, API paths, CSS class names, object keys, comments, and data returned by the API. Duplicate labels are counted per occurrence because each must be migrated or replaced by a shared message key. |

## Internationalization

Current state: the catalog data is live and can contain multilingual metadata, but the app chrome is still English-only. This change adds low-risk primitives: `Intl.*` formatters, a plural/count helper, document `lang`/`dir` plumbing through `toolhub-locale`, `<time>` output, and `dir="auto"` on many API-provided text sinks. The app still needs a message catalog and a locale switcher before it can be considered localized.

### Prioritized findings

| Priority | Issue | Severity | Location | Recommended fix | Effort | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | No message catalog; all shell and route chrome is hardcoded English. | High | `public_html/index.html:7-104`, `public_html/app.js:139-1059` | Add a plain JSON message catalog and replace visible strings with `t(key, params)`. Keep English as fallback. | L | Deferred |
| 2 | API multilingual/localized fields are not selected by requested UI locale; code renders `title`, `description`, facets, and metadata as received. | High | `public_html/app.js:146-155`, `public_html/app.js:430-548`, `public_html/app.js:898-927` | Add a field resolver that prefers the active locale, then language fallback, then default API value. Preserve source language metadata when the API exposes it. | M | Deferred |
| 3 | Dynamic catalog content had no direction handling and still lacks per-field language handling. | High | Fixed in `public_html/app.js:39`, `public_html/app.js:174-212`, `public_html/app.js:262-264`, `public_html/app.js:327`, `public_html/app.js:435-500`, `public_html/app.js:570-571`, `public_html/app.js:747-836`, `public_html/app.js:901-921` | Keep `dir="auto"` on untrusted/API text. Add `lang` when the API identifies a field language. | M | Partly fixed |
| 4 | English sentence interpolation prevents correct word order and grammar in other languages. | High | `public_html/app.js:190`, `public_html/app.js:196`, `public_html/app.js:383`, `public_html/app.js:473`, `public_html/app.js:543`, `public_html/app.js:912` | Move full sentences into messages, for example `toolCard.byMaintainer`, `search.resultsFor`, and `usage.last30Days`. Do not concatenate translated fragments. | M | Deferred |
| 5 | Locale-sensitive dates, relative times, compact numbers, and plurals were English/manual. | Medium | Fixed in `public_html/app.js:29-74`; used at `public_html/app.js:201`, `public_html/app.js:383`, `public_html/app.js:481`, `public_html/app.js:781-790`, `public_html/app.js:918-919` | Continue using `Intl.NumberFormat`, `Intl.RelativeTimeFormat`, `Intl.DateTimeFormat`, and `Intl.PluralRules`; move labels into catalog messages. | S | Fixed primitive |
| 6 | `<html lang>` and `dir` were static, with no runtime locale hook. | Medium | Fixed in `public_html/index.html:2`, `public_html/app.js:22-38`, `public_html/app.js:75` | Add a visible language selector that writes `toolhub-locale`, loads a catalog, and re-renders the current route. | M | Partly fixed |
| 7 | RTL CSS used many physical left/right properties that would not mirror. | Medium | Fixed in `public_html/styles.css:59`, `public_html/styles.css:78-82`, `public_html/styles.css:123-124`, `public_html/styles.css:152`, `public_html/styles.css:194`, `public_html/styles.css:210-218`, `public_html/styles.css:232-242`, `public_html/styles.css:269`, `public_html/styles.css:312`, `public_html/styles.css:375-380`, `public_html/styles.css:396`, `public_html/styles.css:404-410`, `public_html/styles.css:444-482` | Keep using logical properties. Add RTL smoke checks for header, card flags, quick-view, account menu, tables, and the experimental switch. | M | Fixed |
| 8 | Static prose pages are embedded as HTML strings, making translation and review hard. | Medium | `public_html/app.js:577-690` | Extract static pages to message keys or per-locale HTML fragments with a small whitelist/sanitizer. | M | Deferred |
| 9 | Page titles and route stub copy are hardcoded and interpolated in English. | Medium | `public_html/app.js:548`, `public_html/app.js:561`, `public_html/app.js:574`, `public_html/app.js:838`, `public_html/app.js:857-875`, `public_html/app.js:1005-1030`, `public_html/app.js:1057-1059` | Route objects should return message keys and params, not final English titles/copy. | S | Deferred |
| 10 | Facet labels, sort options, pagination labels, and URL-derived query labels are English. | Medium | `public_html/app.js:313-317`, `public_html/app.js:357-366`, `public_html/app.js:373-387` | Catalog facet group labels and sort/pager labels. Keep API facet values as data with `dir="auto"`. | S | Deferred |
| 11 | Icon and punctuation placement can need locale-specific treatment. | Low | Partly fixed in `public_html/index.html:31-32`, `public_html/index.html:75-90`, `public_html/app.js:415`, `public_html/app.js:480-487`, `public_html/app.js:581`, `public_html/app.js:701`, `public_html/app.js:918-926` | Keep icons outside translatable text where decorative; let messages decide punctuation and external-link wording. | S | Partly fixed |
| 12 | Font stack is brand-forward but not checked for every target script. | Low | `public_html/tokens.css:70-71`, `public_html/styles.css:4-12` | Test CJK, Arabic, Hebrew, Indic, and fallback glyph coverage. Add locale-specific font fallbacks only if visual QA shows gaps. | M | Deferred |

### Recommended no-build i18n architecture

Keep it vanilla and dependency-free:

1. Add `public_html/i18n/en.json` with flat message keys:

```json
{
  "nav.browse": "Browse",
  "search.resultsFor": "{count} {count, plural, one {tool} other {tools}} for \"{query}\"",
  "tool.byMaintainer": "by {name}"
}
```

2. Add a small `i18n` module inside `app.js` or a separate `i18n.js` loaded before `app.js`:
   - `loadMessages(locale)` fetches `i18n/{locale}.json`, falling back to `en`.
   - `t(key, params)` resolves a message and escapes params by default.
   - `formatCount`, `formatDate`, `formatRelativeTime`, and `plural` wrap `Intl.*`.
   - `setLocale(locale)` stores `toolhub-locale`, sets `document.documentElement.lang/dir`, reloads messages, and re-renders the current hash route.

3. Do not concatenate translated fragments. Whole sentences should be messages with params. API data stays data and gets `dir="auto"` plus `lang` when known.

4. Use Toolhub/translatewiki-compatible keys from the start. English remains the source catalog; translated JSON can be generated or copied in later.

5. Migration path:
   - Phase 1: move shell/nav/footer/account/search/card strings to `en.json`.
   - Phase 2: move detail, quick-view, list, and parity pages.
   - Phase 3: move static prose pages to locale files.
   - Phase 4: implement localized field selection for Toolhub API data.
   - Phase 5: add a language switcher, pseudolocalization, and an RTL smoke page in local QA.

## Accessibility

Target: WCAG 2.1 AA. The app already had useful foundations: landmarks, skip link, labeled search inputs, keyboard activation for card quick-view, visible focus, reduced-motion CSS, and route-change focus to the page `h1`. This change fixes high-value gaps around modal isolation, loading announcements, active nav state, incorrect dropdown ARIA, icon exposure, and RTL-related layout.

### Prioritized findings

| Priority | Issue | Severity | WCAG criterion | Location | Recommended fix | Effort | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Quick-view dialog did not hide/inert the background from keyboard and assistive tech users. | High | 2.1.2 No Keyboard Trap, 2.4.3 Focus Order, 4.1.2 Name/Role/Value | Fixed in `public_html/index.html:102-104`, `public_html/app.js:889-960` | Keep `aria-modal`, set `aria-hidden` on the modal when closed, set background `inert`/`aria-hidden` while open, trap Tab, support Escape, and restore focus. | M | Fixed |
| 2 | Dynamic route loading had a spinner but no robust status text or busy state on the main region. | High | 4.1.3 Status Messages, 2.4.3 Focus Order | Fixed in `public_html/index.html:51`, `public_html/app.js:1056-1075` | Keep `role="status"` with hidden text and toggle `aria-busy` during route fetches. | S | Fixed |
| 3 | API content could render in the wrong direction and lacked language metadata, affecting screen reader pronunciation for multilingual content. | High | 3.1.2 Language of Parts, 1.3.2 Meaningful Sequence | Partly fixed in `public_html/app.js:39`, `public_html/app.js:174-212`, `public_html/app.js:435-500`, `public_html/app.js:747-836`, `public_html/app.js:901-921` | Keep `dir="auto"`; add per-field `lang` when Toolhub exposes language metadata. | M | Partly fixed |
| 4 | Primary nav active state was visual only and duplicate `#/search` links could both be current. | Medium | 2.4.4 Link Purpose, 4.1.2 Name/Role/Value | Fixed in `public_html/index.html:25-28`, `public_html/app.js:1041-1053` | Use `aria-current="page"` for exactly one active primary nav item. Consider giving Categories a real route or removing the duplicate. | S | Fixed |
| 5 | Account dropdown used `role="menu"`/`menuitem` without menu keyboard behavior. | Medium | 2.1.1 Keyboard, 4.1.2 Name/Role/Value | Fixed in `public_html/app.js:976-1002`, `public_html/app.js:1120-1123`, `public_html/styles.css:78-86` | Use a normal disclosure (`aria-expanded`, `aria-controls`) with native links/buttons, or fully implement ARIA menu keyboard rules. | S | Fixed |
| 6 | Decorative icons and external-link arrows were exposed inconsistently in accessible names. | Medium | 1.1.1 Non-text Content, 4.1.2 Name/Role/Value | Fixed in `public_html/index.html:31-32`, `public_html/index.html:75-90`, `public_html/app.js:415`, `public_html/app.js:480-487`, `public_html/app.js:581`, `public_html/app.js:701`, `public_html/app.js:918-926`, `public_html/app.js:976-988` | Keep decorative glyphs in `aria-hidden` spans; ensure adjacent text carries the accessible name. | S | Fixed |
| 7 | Card grids are visually collections but are not exposed as lists. | Medium | 1.3.1 Info and Relationships | `public_html/app.js:216-217`, used at `public_html/app.js:278-287`, `public_html/app.js:386`, `public_html/app.js:452`, `public_html/app.js:559`, `public_html/app.js:572` | Render grids as `<ul class="card-grid ...">` with `<li>` wrappers, or add list semantics if visual markup must stay. | M | Deferred |
| 8 | Tool cards use `article role="button"` instead of a native button, because the card contains internal tag interactions. | Medium | 2.1.1 Keyboard, 4.1.2 Name/Role/Value | `public_html/app.js:190`, `public_html/app.js:1095-1107` | Current keyboard support works. Longer term, make the card a real link to the tool page and provide a separate quick-view button. | M | Deferred |
| 9 | Crawler history table lacks a caption and explicit `scope` on header cells. | Medium | 1.3.1 Info and Relationships | `public_html/app.js:792-795` | Add `<caption>` and `scope="col"` to headers. | S | Deferred |
| 10 | Static prose pages and long policy content are inserted as HTML strings, limiting automated a11y linting and translation review. | Medium | 1.3.1 Info and Relationships, 3.1.1 Language of Page | `public_html/app.js:577-690` | Move prose content into structured page definitions or localized HTML fragments with reviewable markup. | M | Deferred |
| 11 | Yellow star glyphs have low contrast on white if treated as meaningful text. | Low | 1.4.3 Contrast (Minimum), 1.4.1 Use of Color | `public_html/app.js:517-519`, `public_html/styles.css:487` | Numeric rating `4.2` is present and stars are `aria-hidden`; keep rating meaning in text. If stars become meaningful, use a darker token. | S | Accepted |
| 12 | Focus outline is intentionally suppressed on route-focus headings and `#view`. | Low | 2.4.7 Focus Visible | `public_html/styles.css:360-362`, `public_html/app.js:1080-1085` | This is acceptable for programmatic focus on a heading, but keep visible focus for all interactive controls. | S | Accepted |
| 13 | Reduced-motion support is present but should be regression-tested when new animations are added. | Low | 2.3.3 Animation from Interactions | `public_html/styles.css:494-498`, `public_html/app.js:97-98` | Keep the global reduced-motion override and avoid adding motion-only state changes. | S | Accepted |
| 14 | Search and footer duplicate destinations can confuse link-purpose scanning. | Low | 2.4.4 Link Purpose | `public_html/index.html:26-28`, `public_html/index.html:55-86` | Give duplicate links clearer destinations or labels when real category routes exist. | S | Deferred |

### Contrast notes

Computed contrast ratios against the current tokens:

| Pair | Ratio | Result |
| --- | ---: | --- |
| `--color-text` `#1b1b1b` on white | 17.22:1 | Pass |
| `--color-text-secondary` `#54595d` on white | 7.09:1 | Pass |
| `--color-text-muted` `#5c6066` on white | 6.33:1 | Pass |
| `--color-progressive` `#0c57a8` on white | 7.13:1 | Pass |
| White text on primary blue `#0c57a8` | 7.13:1 | Pass |
| Tag text `#0c57a8` on subtle blue `#e7f0fa` | 6.20:1 | Pass |
| Success text `#246342` on subtle green `#cbe0d5` | 5.16:1 | Pass |
| Destructive text `#970302` on subtle red `#e5c0c0` | 5.42:1 | Pass |
| Warning text `#8a4b08` on subtle orange `#fbdfc5` | 5.33:1 | Pass |
| White on purple badge `#5748b5` | 7.00:1 | Pass |
| Yellow star `#f0bc00` on white | 1.76:1 | Fail if meaningful text |
| Avatar palette with white initials | 4.55:1 minimum | Pass for normal text |

### Verification performed

- `node --check public_html/app.js`
- CSS physical-direction scan: no remaining physical left/right declarations except comments.
- Local Flask proxy on `http://127.0.0.1:8010` with live Toolhub API data.
- Playwright snapshots for home, account disclosure, quick-view dialog, and `#/search?q=commons`.
- Runtime assertions: `html lang="en" dir="ltr"` by default, `toolhub-locale=ar` sets `lang="ar" dir="rtl"`, `#view aria-busy` returns to `false`, only one primary nav item has `aria-current="page"`, quick-view Escape closes the dialog and restores focus to the triggering card, modal opening sets background nodes to `inert` and `aria-hidden=true`.
