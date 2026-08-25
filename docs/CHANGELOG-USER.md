<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-lens-for-the-whole-page -->
<!-- Release title: A Lens for the Whole Page -->
<!-- Source range: 74af2958..eb22a5b6 (1 commit) -->

# What's New for Users

- The statistics page can now be read for user scripts and gadgets alone, or for registered tools alone. It is the whole page that changes, not one chart: the tool count, every documentation percentage, the verified-author and verified-maintainer coverage, the relationship figures and the unresolved-attribution funnel are all recounted against whichever set you picked.
- Until now only the creation-year chart could be narrowed, which left the narrowed chart surrounded by numbers that had not moved. A reader could not tell which figures on the page applied to what they were looking at, and the most interesting questions -- how well documented the wiki lane actually is, how much of it anyone has verified -- had no answer on the page at all.
- Switching is instant. All three readings are prepared together and arrive in the same response, so choosing one redraws the page immediately, without a spinner, and without ever showing you one lane's chart beside another lane's totals.
- The two lanes read very differently, which is the point. Registered tools carry descriptions, URLs, repositories and verified people at a far higher rate than user scripts and gadgets, most of which arrived from a wiki page with little more than a title and a first-revision date. Read as a single average, each was hiding the other.
- A long-standing miscount is fixed along the way. An unresolved author name left behind by a tool the catalog no longer holds was still being counted in the unresolved-labels total. It is no longer counted, under any lens.
