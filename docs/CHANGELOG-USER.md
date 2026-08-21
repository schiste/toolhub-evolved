<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: gadgets-actually-listed -->
<!-- Release title: The Gadget Directory Fills In -->
<!-- Source range: 5143b43..e752848 (2 commits) -->

# What's New for Users

- Gadgets are now actually listed. The directory learned about gadgets in the last release but showed none of them: the query that reads a wiki's gadget definitions asked for the text without asking for the revision id, and the reader discards a revision that arrives without one, so every wiki's definition page was read as blank. French Wikipedia declares 95 gadgets and Meta 75; the count listed was zero.
- Source analysis of a gadget now reads the whole gadget. The same blank read meant a gadget's member files could not be resolved, so scanning fell back to the single page the gadget is named after and never opened the stylesheet or helper scripts alongside it. Findings for multi-file gadgets were drawn from a fraction of their code.
- A census that reads nothing now says which kind of nothing it found. A wiki that refused the request and a page we failed to read were reported identically, which is why a directory that had never listed a single gadget still looked like it was working.
