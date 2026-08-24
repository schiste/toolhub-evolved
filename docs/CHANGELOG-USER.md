<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: every-box-counts -->
<!-- Release title: Every Box Counts -->
<!-- Source range: 2bcf2cfd4..9a2d5fa1b (2 commits) -->

# What's New for Users

- The Status filter has the box it was missing. Last release gave search a Status filter with Archived cleared by default; it could say "not deprecated" and "not experimental" but never "just the healthy ones". There is now an Active box, ticked alongside Deprecated and Experimental, so leaving the filter alone still shows you everything. A tool counts as Active when nothing is flagged against it — a tool's record says what is wrong with it and never says that it is fine, so Active is the absence of the other three rather than a label anyone applies. Clear it to see only the tools carrying a flag.
- The number of tools now follows the filter. Three of those boxes used to be applied in your browser, on results the site had already counted and split into pages. That is why a search could say "showing 1-8 of 21" and then list six, with a line underneath explaining that some had been filtered out after the fact — the count and the pager were describing a larger set than the one you were looking at. Every box is now applied when the results are chosen, so the count, the range and the page numbers describe exactly what is on the page, and that explanatory line is gone.
- Two smaller repairs came with it. A tool that is both deprecated and experimental used to fall through the gap between the boxes and disappear from both; it now shows under either one, which is what the labels say. And when the catalogue is unreachable and search falls back to the last published copy, that copy answers all four boxes rather than only Archived — an outage used to quietly hand back a differently filtered set of results while the page still said it was showing your search.
