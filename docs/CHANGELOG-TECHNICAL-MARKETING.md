<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: where-the-clones-go -->
<!-- Release title: Where the Clones Go -->
<!-- Source range: 0e226079..1f4da052 (1 promoted commit) -->

# Technical and Marketing Notes

- `authorship_backlog` now excludes `PROVIDER_MEDIAWIKI_WIKIMEDIA`. That provider is 26,972 of the 28,324 analyzed rows, so the selection the previous release shipped was 95% work that could not produce a result: `_acquire_wiki` yields no tree to list and no commits to read identities from, and the detector reads exactly those two things.
- The exclusion is about cost as much as yield. A page set has no cheap head — a gadget's file list lives in a page of its own — so the only way to re-read one is to fetch it. That is ~27,000 MediaWiki API reads to leave a column reading "not known", and `_save_failure` turns any transient `maxlag` during the fetch into a row that was `analyzed` becoming `error`.
- This was found by running it, not by reading it. A 50-candidate batch in production returned 35 analyzed and 15 errors, and grouping `last_error` over the window showed all 15 were the identical `wiki API refused the query: maxlag` — a lane-shaped failure, not fifteen dead repositories.
- Wiki rows keep `llm_checked_at` NULL rather than being stamped as looked-at. The column means the layer read the source; asserting it for a source that was never fetched would put a false answer where an honest absent one belongs. Ordinary wiki scans still stamp it, because those did fetch.
- The remaining backlog is 1,352 rows: 722 github, 510 gitlab-wikimedia, 38 gerrit-wikimedia, 31 codeberg, 30 gitlab, 6 bitbucket. That is one bounded run rather than a multi-day one, and it is entirely composed of sources where a marker file or a commit identity can exist.
- Validation: 119 tests across `test_repository_scan.py` and `test_source_authorship.py`, including a new one that seeds one git-hosted and one wiki-hosted analyzed row and asserts the backlog returns only the git one. Full `pytest-proxy` gate passed on the merged tree in 125s.
