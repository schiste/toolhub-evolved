<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: where-the-clones-go -->
<!-- Release title: Where the Clones Go -->
<!-- Source range: 0e226079..1f4da052 (1 promoted commit) -->

# What's New for Users

- The one-time re-read that fills in assistant traces for already-analyzed tools now skips gadgets and user scripts, which are 26,972 of the 28,324 tools it would otherwise have visited.
- Skipping them costs nothing, because there was nothing there to find. A gadget's source is a set of wiki pages: no repository, no commit history, nothing for this check to read. Re-reading one would have left the answer exactly where it already is — "not known".
- Visiting them would have cost something, though. A page set can only be re-read by fetching it, so this would have made about 27,000 requests to the wikis, and every one the wiki declined for lag would have marked a tool as failing when nothing was wrong with it.
- A 50-tool trial run found precisely that: 15 of the 50 came back as wiki lag errors rather than results, which is what prompted the change before the full run.
- What remains is the 1,352 tools that are actually kept in a repository, which is the whole of the work that can answer the question.
