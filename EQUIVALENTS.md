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
- **author-index.js** — `authorObjs`/`authors` co-emptiness invariant from
  `normalizeTool`, `tools||[]` defaults, `[]`-vs-`undefined` indistinguishable via `||[]`.
- **signals.js** — never-rejecting `.catch`, `||[]` array fallbacks that a
  sentinel can't match, stable-sort index tiebreak (`-` vs `+` preserves order).
- **store.js** — `demoRevisionsFor` default `[]` arg immediately filtered by `content_id`.
- **theme.js** — always-true DOM-guard under the test environment, `"system"`
  vs `""` resolve identically.

Run `grep -rn "Stryker disable" public_html/` for the exact lines and reasons.
