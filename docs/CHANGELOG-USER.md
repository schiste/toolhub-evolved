<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: search-that-finds-the-obvious -->
<!-- Release title: Search That Finds The Obvious -->
<!-- Source range: c9576a7e..15357184 (4 commits) -->

# What's New for Users

- Search now puts the best match first. The catalog is mostly gadgets and user scripts, and their names sort ahead of everything else, so a search listed them first whatever you typed: XTools itself sat at position 81 of 97 for "xtools", and ORES Inspect at 89 of 120 for "ores". A tool whose title is exactly what you typed now comes first, then tools with the word in their title, then in their keywords, then in their description.
- The keywords an author wrote are finally searched. One tool describes itself as making "a CSV with pageview data" and lists "pageviews" as a keyword; a search for "pageviews" could not find it, because keywords were never indexed and the plural does not occur in the prose. Keywords now count, and rank above a passing mention in a description.
- Whole words beat fragments of longer ones. "ores" used to be led by every tool that stores, scores or restores something; those still appear, but after the tools that are actually about ORES. A plural finds its singular and the other way round, so "citations" and "citation" reach the same tools.
- A half-remembered query gets an answer instead of nothing. "copyright violation" returned three tools and left out every copyright checker that never says "violation". Tools containing all your words still come first, and the ones containing some of them follow, so the result count grows: read the first page rather than the number.
- Choosing to sort by name or by date still does exactly that. Relevance is the order when you have typed a query and picked no other, which is also what the official Toolhub does.
