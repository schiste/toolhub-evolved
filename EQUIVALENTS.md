# Equivalent mutants

Pursuing a literal 100% Stryker mutation score means a small number of mutants
are genuinely **equivalent** — the mutation produces behaviour that is
indistinguishable from the original, so no test can kill it without asserting on
private implementation detail. Each is suppressed at its source line with:

```js
// Stryker disable next-line <Mutator> — <one-line reason it is equivalent>
```

These are the project's only in-code suppressions, and every one carries a
justification on the same line (grep `Stryker disable` to audit them). They are
used sparingly and only where a killing test is genuinely impossible.

## By module (core)

- **similarity.js** — commutative min/max selection in `cosine`/shared-terms,
  `||1` IDF fallback equal to a unit weight, never-rejecting memoized `.catch`,
  pre-filtered empty-vector guards.
- **dom.js** — abs-symmetric `+`/`-` in the FNV-style `hash`, redundant
  anchors in already-gated regexes, unreachable `catch`, `String(null)`-isn't-a-URL guard.
- **routing.js** — `||"/"` / `path===""` fallbacks (pathname is never empty),
  ignored history `title` argument.
- **author-index.js** — the author-list / author-object co-emptiness invariant
  from `normalizeTool`, `tools||[]` defaults, `[]`-vs-`undefined` indistinguishable via `||[]`.
- **signals.js** — never-rejecting `.catch`, `||[]` array fallbacks that a
  sentinel can't match, stable-sort index tiebreak (`-` vs `+` preserves order).
- **store.js** — `demoRevisionsFor` default `[]` arg immediately filtered by `content_id`.
- **theme.js** — always-true DOM-guard under the test environment, `"system"`
  vs `""` resolve identically.
- **graph.js** — the symmetric/empty-vector cosine invariants make most knnEdges
  guards unobservable; in detectCommunities a uniformly-injected phantom member
  (NaN weight / undefined id) never wins and extra propagation passes converge
  identically; label/regex fallbacks on always-present values.

## By module (atoms / molecules)

- **button.js** — `variant||"outline"` / `size||"md"` where the consumer does
  `Map.get(x)||Map.get(default)` (so `""` maps identically); `outboundHref`
  dead `||""` (only reached when href is truthy); `.split(/\s+/)`→`/\s/`
  identical after `.filter(Boolean)`; `tag==="a"` redundant with `outboundHref`.
- **avatar.js** — dead `||""` fallbacks in commonsThumb/isCommonsFilePageUrl/
  isDirectImageUrl; a decode-failure `catch` body that re-assigns the same value.
- **form-fields.js** — `value===null||value===undefined?"":value` is redundant
  because `esc()` already coerces null/undefined to `""`.
- **labels.js** — unreachable `wikiShort` plural (length≥2 only), `slice(0,undefined)`
  = full copy, `linkOut` variant Map double-fallback.
- **badges.js** — default `level:"green"` (statusClasses maps any unknown to green).
- **signals.js (atoms)** — `synthThanks`/`synthUsage` ranges never equal 1, so the
  plural `one` form is unreachable.
- **facet-group.js** — `buckets||[]` sentinel element is dropped by `.filter()`.

## By module (organisms)

- **account.js / quickview.js** — `variant:"outline"` literals that `button()`
  defaults anyway; `"inert" in el` always true; the post-open focus-guard's
  false branch and the empty-`f` early return in the focus trap are unreachable.
- **langpicker.js** — `activeEntry()` always resolves to `LANGUAGES[0]` (English).
- **force-graph.js** — the canvas-only machinery (`colorForNode`, `buildColors`,
  the `draw*` functions, edge/neighbor bookkeeping, fallback colours) whose only
  output is `ctx.*` draw calls with no assertable effect; plus environment-fixed
  equivalents (`dpr===1`, pre-trimmed CSS, measure-zero hit-test boundaries) and
  state overwritten before it can be observed (initial size/pointer, re-settle).

## By module (views + main.js)

- **all views** — `button()` default `variant`/`size` literals (the atom
  re-supplies them); defensive `||[]` / `||""` on data that normalizeTool/
  normalizeList/nearestNeighbors already guarantee; `.catch(() => ({results:[]}))`
  shapes read only as `.results||[]`; unreachable post-render DOM guards
  (`if (!el)` on elements just rendered into the view).
- **search.js** — `??""` parse fallbacks (NaN either way), `-score`→relevance
  only reachable when relevance is already the default (experimental on).
- **toolforms.js** — pre-trimmed URL inputs, blank-draft fields that render empty.
- **router.js** — `clearTimeout(null)` no-op guard.
- **parity.js** — missing `show` re-derives to `"all"`; catch-fallback shapes
  read only via `.results||[]` / `.count||0`.

Run `grep -rn "Stryker disable" public_html/` for the exact lines and reasons.
