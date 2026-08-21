<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: source-labels-complete -->
<!-- Release title: Every Source Says Its Name -->
<!-- Source range: e83a9a2..bf8b687 (1 commit) -->

# Technical Release Notes

- Adds `wikimedia_user_script` to `CATALOG_SOURCE_LABELS` in `views/tool.js` and to `sourceLabels` in `views/toolforms.js`, each in that file's existing idiom -- a literal string in the first, a `t()` lookup in the second -- with `toolforms.sourceWikimediaUserScript` documented in en and qqq. `catalog_projection` attaches this source to any canonical row whose `url` is a user-space JavaScript page, so it reaches the evidence panel and the effective-source note on every user script in the catalogue.
- Both maps fall back to `row.source`, which is why this shipped twice: a source constant added in Python with no label in JavaScript breaks nothing, fails no test, and renders an internal identifier to the reader. The fallback is kept -- it is the right behaviour for an unknown key -- but it is no longer the only thing standing between a new source and a raw string on a tool page.
- Adds a test that every key of `SOURCE_CONFIDENCE` appears in both label maps, parameterized over the two files and reading them from disk. Neither map is reachable from Python by import, so stating the invariant means crossing the language boundary; removing either label now fails by name rather than silently degrading a page.
