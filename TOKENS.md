# Design tokens

Single source of truth: **`tokens.css`**. Every colour, font, radius and
shadow in the UI comes from here. **Components must never hard-code a hex** — add
or extend a token instead, so the whole app (and every future page/template)
stays on-brand from one place.

**Layers** — always consume the highest one you can:

1. **Raw brand palette** `--wmf-*` — verbatim from the Wikimedia brand guidelines.
2. **Semantic tokens** `--color-* / --font-* / --radius-* / --shadow-*` — what components reference.
3. **Compat aliases** (`--accent`, `--base10`, …) — legacy names mapped to layer 2; deprecated, don't use in new code.

Sources: [Brand/colors](https://meta.wikimedia.org/wiki/Brand/colors) · [Brand/Typography](https://meta.wikimedia.org/wiki/Brand/Typography) (2022 palette).

---

## 1. Raw brand palette (`--wmf-*`)

**Core neutrals**

| Token | Hex |
|---|---|
| `--wmf-white` | `#ffffff` |

**Movement colours** (`*-aaa` are tuned to pass on white)

| Token | Hex |
|---|---|
| `--wmf-green-aaa` | `#246342` |
| `--wmf-blue-aaa` | `#0c57a8` |
| `--wmf-red-aaa` | `#970302` |

**Creative — strong** (accents): `--wmf-orange #ee8019`, `--wmf-yellow #f0bc00`, `--wmf-purple #5748b5`.

**Creative — light** (subtle backgrounds, pair with dark text): `--wmf-red-light #e5c0c0`, `--wmf-orange-light #fbdfc5`, `--wmf-green-light #cbe0d5`.

---

## 2. Semantic tokens (use these)

| Token | Resolves to | Used for | AA on… |
|---|---|---|---|
| `--color-surface` | `--wmf-white` | page / card background | — |
| `--color-surface-muted` | `#f4f5f7` *(derived)* | faint fills, dividers | — |
| `--color-border` | `#d4d7db` *(derived)* | hairlines, card borders | — |
| `--color-text` | `#1b1b1b` *(derived)* | body text | 16.8:1 on white |
| `--color-text-secondary` | `#54595d` *(derived)* | descriptions | 7.1:1 |
| `--color-text-muted` | `#5c6066` *(derived)* | meta, captions (small) | 5.0:1 |
| `--color-progressive` | `--wmf-blue-aaa` `#0c57a8` | links, primary buttons, tags | 7.1:1 on white |
| `--color-progressive-hover` | `#09437f` *(derived)* | hover state | — |
| `--color-progressive-subtle` | `#e7f0fa` *(derived)* | tag/chip background | text 6.2:1 |
| `--color-success` | `--wmf-green-aaa` | "Healthy" text + dot | 5.2:1 on subtle |
| `--color-success-subtle` | `--wmf-green-light` | "Healthy" pill bg | — |
| `--color-destructive` | `--wmf-red-aaa` | "Deprecated" text + dot | 5.4:1 on subtle |
| `--color-destructive-subtle` | `--wmf-red-light` | "Deprecated" pill bg | — |
| `--color-warning` | `--wmf-orange` | warning dot | — |
| `--color-warning-text` | `#8a4b08` *(derived)* | "Experimental" text | 5.3:1 on subtle |
| `--color-warning-subtle` | `--wmf-orange-light` | "Experimental" pill bg | — |

**Radius** (φ-stepped Fibonacci subset) — `--radius-sm 8` · `--radius-md 13` · `--radius-lg 21` · `--radius-pill 999px`.

**Type** (φ modular scale from a 16px base) — `--fs-caption 13` · `--fs-body 16` · `--fs-title 26` (16×φ) · `--fs-display 42` (16×φ²).

**Typography families** — `--font-sans` = Montserrat (headings + UI), `--font-serif` = Source Serif 4 (prose, via the `.prose` class). Weight token: `--font-weight-bold 700`. (i18n: Noto for non-Latin scripts.)

**Elevation** — `--shadow` (resting), `--shadow-hover` (lifted).

---

## 3. Compat aliases (deprecated)

`--white --base10 --base20 --base30 --base80 --base90 --accent --accent-hover --accent90 --yellow30 --radius` → mapped to layer-2 tokens for back-compat. **Don't use in new code.**

---

## Adding a token

1. If it's a brand value, add the raw hex under layer 1 as `--wmf-…` (cite the brand page).
2. Expose a **semantic** token in layer 2 that references it (e.g. `--color-…: var(--wmf-…)`).
3. Reference only the semantic token from component CSS. Verify text/background pairs hit **WCAG AA (4.5:1)** — see the AA column above for the pattern.

*Derived* values (marked above) are neutral/tint adjustments not given literally by the brand; keep them minimal and documented here.
