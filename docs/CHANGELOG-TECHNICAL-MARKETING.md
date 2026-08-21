<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: gadgets-actually-listed -->
<!-- Release title: The Gadget Directory Fills In -->
<!-- Source range: 5143b43..e752848 (2 commits) -->

# Technical Release Notes

- Both gadget definition queries now name `ids` in `rvprop`, through a shared `DEFINITION_REVISION_PARAMS`. `wiki_api._revision` drops any revision without an integer `revid`, so asking for content alone produced payloads that parsed to the empty string: `gadget_inventory.ingest` recorded `read=no` for every wiki and the first production census stored 0 gadgets while exiting 0.
- Omitting the id had been deliberate, to keep the definition page's revision out of a tool's head, but the request was the wrong enforcement point. `definition_text` returns wikitext and discards the `Revision` entirely, so no id can reach a head regardless of what the query asks for; the invariant is unchanged and now holds structurally rather than by starving the parser.
- `repository_scan._wiki_revisions` read the same page through `definition_url` and hit the same blank result, so `wiki_sources.gadget_pages` resolved no members and every gadget scan took the `(source.title,)` fallback. Multi-file gadgets were analyzed as one file.
- The fakes are why this passed review: each supplied a `revid` the query never requested, so the request and its parser drifted apart with the suite green. They now build their response from the `rvprop` they are handed, and reverting just the parameter fails 13 tests across `test_wiki_api`, `test_gadget_inventory` and `test_gadget_census` where before it failed none.
- `ingest` now carries a reason on every summary -- `read`, `request-failed` or `no-definition` -- printed on the census line for successful runs too, so a lane discarding every response no longer logs identically to a lane whose wikis are all down.
