<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-half-that-was-never-read -->
<!-- Release title: The Half That Was Never Read -->
<!-- Source range: c1980f8..7f2cb28 (2 commits) -->

# What's New for Users

- Evolved's directory of Wikipedia user scripts now covers English Wikipedia, alongside French Wikipedia and Meta. That matters because English Wikipedia is where the largest population of user scripts is written, so it is where a script someone is about to write is most likely to already exist under another name.
- Meta's coverage was quietly incomplete. Evolved found script pages by asking Wikipedia's search index, and that index refuses to page past its ten-thousandth result, so Evolved was reading about 500 of Meta's 25,354 script pages. Nothing it showed you was wrong -- it said plainly that it had read only part of the wiki -- but most of that wiki was simply invisible to it.
- Evolved now reads the list of pages from the Wikimedia databases directly, which answers the same question exactly and with no limit. It also asks each page what kind of content it holds rather than guessing from the filename, which finds the twenty to sixty pages per wiki that hold JavaScript under a name not ending in `.js`, and skips the ordinary wiki pages that do.
- Wikis too large to read in one go are now read across several runs, each picking up where the last one stopped rather than starting over. English Wikipedia's 155,561 script pages take about three days to read the first time, and minutes an hour to stay current afterwards.
- A wiki is only treated as fully surveyed by the run that reaches its last page, so a script is never marked as removed on the strength of a partial reading. Until that run happens the directory says which wikis it has finished and which it is still working through.
