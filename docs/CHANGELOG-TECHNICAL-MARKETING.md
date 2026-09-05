<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: audiences-say-where-they-came-from -->
<!-- Release title: Audiences Say Where They Came From -->
<!-- Source range: 06066c16..HEAD -->

# Technical and Marketing Notes

- The Audiences row was the one derived detail in that block rendering without `mark(...)`. Type, Works on and Technology all carry it; audiences shipped inferred, at a measured 0.87 precision across what will become roughly 51,000 records, displaying as though a maintainer had set them.
- A per-field `sourceMark` is correct here where keywords needed a per-value `valueMark`. `_assemble` only makes its fill-only exception for `keywords`, so inference can never extend a non-empty `audiences` list — an inferred audience is always the whole field, and the field's effective row is the one to ask.
- Two tests, in both directions: an inferred audience carries the mark and names the gadget lane's own wording, and one credited to `official_toolhub` carries none. The second is what stops a later simplification marking every audience indiscriminately, which would be as misleading as marking none.
- This is the third defect in this family found by looking at the rendered page rather than the data layer — after keywords rendering unmarked, and the gadget tooltip naming source code that was never read. The data was right in all three; what was missing was the sentence next to it. Checking the projection payload proves nothing about what a reader sees.
- Validation: 1,409 vitest tests, eslint, `tsc --checkJs`, prettier and cspell clean. Existing records re-mark on their next projection rebuild, which the backfill is already driving.
