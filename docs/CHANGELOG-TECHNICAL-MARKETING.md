<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-registered-tool-wins-the-tie -->
<!-- Release title: The Registered Tool Wins The Tie -->
<!-- Source range: 086e2977..b2c0ae29 (3 commits) -->

# Technical and Marketing Notes

- The tie-break is one more ORDER BY term between the relevance score and the title-length norm: rows whose `source` is `wiki_gadget` or `wiki_userscript` sort after registered rows (`official`, `local`) when their scores are equal. It is a CASE expression on an existing column, costs nothing measurable, and cannot reorder rows whose scores differ.
- Measured on production before the change, with the first ranking release live: "xtools" returned 98 rows with XTools at position 8 behind seven gadgets titled "XTools", each carrying the same exact-title bonus. The gadget rows are the census's record of a wiki linking to the tool, which is why they tie: they are the same tool seen from a second place, and the registered record is the one a reader means.
- The test seeds the XTools case and an ORES case side by side, so the assertion covers both halves of the contract: the registered tool wins the tie, and a census row that scores higher on the signals themselves keeps its place. Search-related suites: 112 passed; ruff clean; broker gates at promotion.
