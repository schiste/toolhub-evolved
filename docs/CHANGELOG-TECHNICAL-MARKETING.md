<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: invisible-character-collisions -->
<!-- Release title: Scripts That Differ by Nothing You Can See -->
<!-- Source range: 1b72aee..4afa859 (7 commits) -->

# Technical Release Notes

- Drops Unicode format characters (category Cf) in `userscripts.canonical_title` and `_resolve`. Meta's census aborted on a duplicate-key `IntegrityError`: a `global.js` there loads `User:Hoo man/tagger.js` twice, once with a trailing U+200E, and `script_imports` dedupes on the Python tuple where the two strings differ while MySQL's collation ignores the mark and its unique key saw one row. The whole wiki's ingest rolled back each pass.
- Applies the same strip in `wiki_sources.canonical_title`, where the failure was silent rather than loud. A mark lands after the extension, `.js` stops being the suffix, `_is_source_title` rejects the title and `wiki_source` returns `None`, so `repository_scan` did not recognize the tool as wiki-hosted and dropped it from enrichment. The strip runs after `unquote`, because a URL copied from a browser bar carries the mark percent-encoded.
- Moves the strip into `backend.wikimedia_urls` as `without_format_marks`, next to the `canonical_username` and `normalized_username` spelling rules it belongs with. Both `canonical_title` functions now share one definition; the alternative was a second copy of a rule whose first copy had already been shown to be reachable from paths that did not have it.
- Records at the import `INSERT` that the Python dedup key matches the table's unique key only while every title and URL reaching it is already in storage's spelling. The comment there previously asserted the match unconditionally, which is the belief the abort disproved.
- Notes in the same place that the suite runs on SQLite, which compares text byte by byte and therefore cannot fail on a collation disagreement. Every bug in this class is invisible to the tests and appears only against MySQL on Toolforge.
