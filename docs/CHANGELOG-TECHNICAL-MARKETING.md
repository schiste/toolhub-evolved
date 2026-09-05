<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: one-empty-answer-is-not-a-blank-record -->
<!-- Release title: One Empty Answer Is Not A Blank Record -->
<!-- Source range: c2635a0e..HEAD -->

# Technical and Marketing Notes

- `record` took the row's status from the outcome of the last question put to it. That was harmless while every ask covered every field, and wrong the moment one could cover a single field: an audiences-only re-ask finding no publishable audience returns `rejected`, and it demoted rows that already held an accepted description and keywords. `catalog_projection` reads an inference row only while it is `ready`, so 1,479 rows were primed to publish nothing at their next rebuild, values intact in their payloads.
- The status now describes the row: `ready` whenever the merged payload holds anything, and the outcome's own status only when it holds nothing. The payload was already merged for exactly this reason -- half the fix shipped and half did not, which is the whole defect.
- Nothing had been lost yet, and the reason is worth recording: a rejected ask produces no enriched names, so those rows were never in the republish list. The damage was latent, waiting on the hourly projection pass to reach each row. Confirmed read-only by assembling one row's sources without writing them -- the rebuild would have published no description and no keywords.
- `proxy/migrate.py` restores the demoted rows rather than recomputing them, since the payloads were always correct. Narrow on purpose: a row with an empty payload keeps its `rejected`, because for that row it is true, and it is what keeps unanswerable pages out of the window.
- A row holding values whose re-ask errored is now `ready` too, and so loses the six-hour error backoff -- it is re-asked through the missing-field arm instead, the lowest tier in the window. Re-asking those sooner than necessary during an outage is the better trade against withdrawing what they already say.
- Found by reading a run summary rather than by a test: `ready` fell 36,496 to 35,912 while `rejected` rose 3,983 to 4,487, in a run that was otherwise a success. The counters that made it visible are the per-lane ones added a day earlier for a different reason.
- Validation: 3,787 proxy and tooling tests with `inference_enrichment` at 100% statement and branch coverage, including that an empty partial ask leaves an answered row published, and that a row holding nothing is still recorded as refused.
