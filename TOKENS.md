# Design tokens

Single source of truth: **`public_html/styles/tokens.css`**. Every colour, font,
spacing step, radius, focus ring and shadow in the UI comes from here.
Components must never hard-code a hex or rgba value. Add or extend a token
instead, so the whole app stays on-brand from one place.

**Layers** — always consume the highest one you can:

1. **Raw brand palette** `--wmf-*` — verbatim from the Wikimedia brand guidelines.
2. **Semantic tokens** `--color-* / --font-* / --space-* / --radius-* / --shadow-* / --focus-*` — what components reference.
3. **Compat aliases** (`--accent`, `--base10`, …) — legacy names mapped to layer 2; deprecated, don't use in new code.

Sources: [Brand/colors](https://meta.wikimedia.org/wiki/Brand/colors) · [Brand/Typography](https://meta.wikimedia.org/wiki/Brand/Typography) (2022 palette).

---

## 1. Raw brand palette (`--wmf-*`)

**Core neutrals**

| Token         | Hex       |
| ------------- | --------- |
| `--wmf-white` | `#ffffff` |

**Movement colours** (`*-aaa` are tuned to pass on white)

| Token             | Hex       |
| ----------------- | --------- |
| `--wmf-green-aaa` | `#246342` |
| `--wmf-blue-aaa`  | `#0c57a8` |
| `--wmf-red-aaa`   | `#970302` |

**Creative — strong** (accents): `--wmf-orange #ee8019`, `--wmf-yellow #f0bc00`, `--wmf-purple #5748b5`.

**Creative — light** (subtle backgrounds, pair with dark text): `--wmf-red-light #e5c0c0`, `--wmf-orange-light #fbdfc5`, `--wmf-green-light #cbe0d5`.

---

## 2. Semantic tokens (use these)

| Token                        | Resolves to                      | Used for                                                |
| ---------------------------- | -------------------------------- | ------------------------------------------------------- |
| `--color-surface`            | `--wmf-white`                    | page, card, popover backgrounds and white-on-color text |
| `--color-surface-muted`      | `#f4f5f7` _(derived)_            | faint fills and dividers                                |
| `--color-surface-pattern`    | `#eef0f3` _(derived)_            | screenshot placeholder stripe                           |
| `--color-row-hover`          | `rgba(0,0,0,.02)` _(derived)_    | table row hover                                         |
| `--color-overlay-modal`      | `rgba(16,20,30,.55)` _(derived)_ | quick-view backdrop                                     |
| `--color-badge-neutral`      | `rgba(0,0,0,.12)` _(derived)_    | neutral demo/mock badges                                |
| `--color-border`             | `#d4d7db` _(derived)_            | hairlines, field borders, resting card borders          |
| `--color-border-hover`       | `#b9c6e6` _(derived)_            | lifted card/link-card border hover                      |
| `--color-border-accent`      | `#cfe0ff` _(derived)_            | CTA panel border on subtle blue                         |
| `--color-text`               | `#1b1b1b` _(derived)_            | body text                                               |
| `--color-text-secondary`     | `#54595d` _(derived)_            | descriptions                                            |
| `--color-text-muted`         | `#5c6066` _(derived)_            | meta, captions                                          |
| `--color-progressive`        | `--wmf-blue-aaa`                 | links, primary buttons, tags                            |
| `--color-progressive-hover`  | `#09437f` _(derived)_            | primary action hover                                    |
| `--color-progressive-subtle` | `#e7f0fa` _(derived)_            | resting progressive chips and hero tint                 |
| `--color-interactive-subtle` | `#dbe7ff` _(derived)_            | tag hover and focus ring wash                           |
| `--color-hero-tint`          | `#f5f9ff` _(derived)_            | hero gradient midpoint                                  |
| `--color-favorite`           | `#b8860b` _(derived)_            | saved/favorite state                                    |
| `--color-success`            | `--wmf-green-aaa`                | healthy/success text and dots                           |
| `--color-success-subtle`     | `--wmf-green-light`              | success pill background                                 |
| `--color-destructive`        | `--wmf-red-aaa`                  | deprecated/destructive text and dots                    |
| `--color-destructive-subtle` | `--wmf-red-light`                | destructive pill background                             |
| `--color-warning`            | `--wmf-orange`                   | warning dot                                             |
| `--color-warning-text`       | `#8a4b08` _(derived)_            | warning text on subtle warning backgrounds              |
| `--color-warning-subtle`     | `--wmf-orange-light`             | warning pill background                                 |

**Spacing** — Fibonacci-like steps aligned to the existing Toolhub rhythm:
`--space-0 0`, `--space-1 4px`, `--space-2 8px`, `--space-3 13px`,
`--space-4 21px`, `--space-5 34px`, `--space-6 56px`, `--space-7 72px`,
`--space-8 89px`.

**Radius** — `--radius-sm 8px`, `--radius-md 13px`, `--radius-lg 21px`,
`--radius-pill 999px`.

**Type** — `--fs-caption 13px`, `--fs-body 16px`, `--fs-subtitle 21px`,
`--fs-title 26px`, `--fs-headline 34px`, `--fs-display 42px`. Families:
`--font-sans` = native system sans (Wikimedia/Codex stack) for headings/UI,
`--font-serif` = system serif (Linux Libertine / Georgia) for prose. Weight token:
`--font-weight-bold 700`.

**Elevation** — `--shadow` (resting), `--shadow-hover` (lifted cards),
`--shadow-popover` (menus and quick card affordances), `--shadow-modal`
(quick-view dialog), `--shadow-sm` (small control thumb).

**Focus** — `--focus-ring` is the shared keyboard focus treatment for links,
buttons, inputs, role-button cards and composed controls.

---

## 3. Compat aliases (deprecated)

`--white --base10 --base20 --base30 --base80 --base90 --base95 --accent --accent-hover --accent90 --yellow30 --radius` → mapped to layer-2 tokens for back-compat. **Don't use in new code.**

---

## Adding a token

1. If it's a brand value, add the raw hex under layer 1 as `--wmf-…` and cite the brand page.
2. Expose a semantic token in layer 2 that references it.
3. Reference only the semantic token from component CSS.
4. Verify text/background pairs hit WCAG AA where text is involved.

_Derived_ values are neutral/tint adjustments not given literally by the brand;
keep them minimal and documented here.
