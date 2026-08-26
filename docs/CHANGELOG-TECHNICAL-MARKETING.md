<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: directory-opens-again -->
<!-- Release title: The Directory Opens Again -->
<!-- Source range: a136925d..4078c267 (1 commit) -->

# Technical and Marketing Notes

- `/v1/userscripts/wikis/` called `coverage()` once per wiki, and `coverage()` is four queries -- one of them a `COUNT` over `user_script_pages`, now a quarter of a million rows. At the three wikis the census was configured for that was 14 queries. Across the 1,015 wikis it has now touched it was over 4,000, and the endpoint took 14-16s wall (`Server-Timing: app;dur=14322`).
- `fetchRead` bounds every render-gating read at `READ_TIMEOUT_MS = 12_000`. The endpoint crossed that line, so the abort fired on every visit and the view took its `failed` branch. The endpoint was never wrong -- only linear in a number that grew by two orders of magnitude -- which is why nothing in the response body changed and the regression test counts queries instead of comparing output.
- `_all_coverage()` groups the same four reads by wiki and stitches them in Python: census states, page counts, directory counts by tier, and newest `computed_at`. Four queries at any roster size. `coverage()` keeps its per-wiki shape for the single-wiki endpoints, and both build their record through one `_coverage_row()` so the two readers cannot drift.
- The cost test asserts the listing issues the same number of queries at 3 wikis and at 30. Against the previous implementation that is 14 and 122; a third test pins the bulk reader's output against the per-wiki `coverage()` it replaced, wiki by wiki, since four grouped reads stitched by key can fail in ways one wiki cannot show.
- `defaultWiki()` chose the first entry with `active + archive > 0`. That was `fr.wikipedia.org` at three configured wikis and is `aa.wikibooks.org` at 1,015 -- one archived page and zero in the tier the page opens on. It now ranks by the tier being rendered, falls back to the busiest wiki overall, then to the first listed, and takes the tier as an argument so `?tier=archive` no longer selects for `active`.
- Both defects share one root: a rule that was correct for a hand-written three-entry list and silently wrong for a self-maintaining roster of a thousand. Neither surfaced in tests because both fixtures were single-wiki; the new tests are multi-wiki on purpose.
