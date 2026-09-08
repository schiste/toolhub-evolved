<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-registered-tool-wins-the-tie -->
<!-- Release title: The Registered Tool Wins The Tie -->
<!-- Source range: 086e2977..b2c0ae29 (3 commits) -->

# What's New for Users

- A search for a tool by its own name now lists the tool itself before the wiki gadgets that link to it. After this morning's ranking release, "xtools" still put XTools eighth: seven wikis each ship a gadget titled exactly "XTools", every one a shortcut to the tool, and with nothing else to separate them the list fell back to alphabetical order, where "gadget-" comes first.
- Only true ties are affected. A gadget that matches your words better than a registered tool still comes first, so a gadget titled "ORES" keeps its place above "ORES Inspect". The change decides who wins when the catalog cannot tell two rows apart, and nothing else.
- Everything from the relevance release stays as it was: the best match first, keywords searched, whole words above fragments, and an answer for a half-remembered query. This is a small correction to it, measured on the live site and shipped the same day.
