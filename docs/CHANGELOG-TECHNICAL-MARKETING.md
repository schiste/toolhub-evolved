<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-licence-line-says-so-too -->
<!-- Release title: The Licence Line Says So Too -->
<!-- Source range: 4f9c0f0c..HEAD -->

# Technical and Marketing Notes

- Four defects of one shape shipped in two days: keywords rendering unmarked, the gadget tooltip naming source code that was never read, the audiences row unmarked, and `license` still unmarked. The data was right every time. What was missing was the sentence beside it, and every one was found by opening the page rather than by a test — the payload always looked correct, because it was.
- The check is now on the page. Every row in the Details block is declared as either backed by a projection field, in which case a derived value must carry a mark, or as not coming from the projection at all, in which case it must not. Both directions are asserted: marking everything misleads exactly as much as marking nothing, since the mark means "not from a toolinfo.json".
- A fourth test is the self-maintaining half. It asserts every rendered row appears in that declaration, so a row added without anybody deciding which kind it is fails rather than defaulting to silence. The gate was written before the fix and failed on `License`; removing the mark from `tool_type` afterwards proved it catches a field it was not written against.
- `tools/field_reach.py` answers the other question the same two days kept asking: how many records does this actually reach today? The inferred keyword floor was sound and moved one tool; `audiences` was sound and reached 140 records an hour out of 51,266. Both were counted afterwards, from probes written from scratch each time -- eight of them.
- Reach is reported per lane, never averaged, because the average is what hides the gap. Run against production it reads `audiences` at 16.3% covered with 48,415 empty -- 37,950 of them user scripts -- and attributes every filled value to the source that won it: `llm_inference=9166, official_toolhub=229`. The `empty` column is the population a change can reach; the source breakdown is who is answering once it has.
- Validation: 1,413 vitest tests and 113 tooling tests, eslint, `tsc --checkJs`, prettier and cspell clean. The reach tool was run against the live catalogue and its checkout restored; its own tests cover the per-lane split, the unattributed-value case, and refusing a misspelled field before complaining about the environment.
