<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: every-wiki-at-once -->
<!-- Release title: Every Wiki at Once -->
<!-- Source range: a9922a0b..6a29146e (2 commits) -->

# Technical and Marketing Notes

- `/v1/userscripts/directory/` required a `wiki` and answered 400 without one. It is optional now: omitting it reads the whole census as one ranking. Rows stay `(wiki, script)` pairs rather than folding on name — `popups.js` on en.wp and fr.wp are different scripts with different code, owners and readers, and merging them would invent a number neither wiki reports.
- Cross-wiki order comes from `demand`, not `position`. `position` is a rank _within_ a wiki, so every wiki has a row at 1; ordering the union by it would interleave 897 unrelated ladders. `wiki` and `title` break ties so paging is stable rather than merely sorted.
- Both tiebreaks descend, like `demand`. The order they impose is arbitrary — they exist for stability — but one index can only be scanned in one direction, and mixing directions would make them unusable and put a filesort over the whole tier in front of every page. `ix_user_script_directory_demand` carries all four columns, and is registered with `_ensure_catalog_read_indexes` because `create_all` skips a table that already exists and this one has been in production for weeks.
- A cross-wiki read answers `coverage: null`. There is no single sweep for it to describe, and stitching 897 records together here would state something true of no wiki while duplicating what `/v1/userscripts/wikis/` already hands the caller.
- `defaultWiki()` is gone, one release after it was fixed. Choosing the busiest wiki in the rendered tier was a better answer than choosing the alphabetically first, but both answer a question the reader never asked — and at 897 wikis holding entries, the busiest one is 21.4% of the directory. Opening on all of it needs no rule and cannot be wrong about intent.
- The view aggregates the roster itself for the strip above the table, and only some of the record survives merging. Counts add: pages seen, scripts per tier. Dates are taken at their oldest and labelled as floors; `sweptAt` is dropped rather than averaged. The two per-wiki partial-coverage notices become counts, because "some of these counts are a floor" is a different claim from "this count is a floor".
- Scale: 45,679 directory rows across 897 wikis, 9,455 active and 36,224 archive. A tier read is an index range with an early stop at 25, so the whole-census reading costs about what a single-wiki one did.
- Validation: `pytest tests/proxy -q` 3181 passed / 25 skipped; `npm run test:unit` 1331 passed across 83 files. Five new endpoint tests, one new migrate test that drops the index and asserts the migration restores it, and six new view tests. Every remaining single-wiki view test now names its wiki in the URL — the old default made that implicit, which is why a change of default touched them at all.
