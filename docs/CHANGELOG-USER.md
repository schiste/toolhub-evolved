<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-licence-nobody-wrote-down -->
<!-- Release title: The Licence Nobody Wrote Down -->
<!-- Source range: 62afe4b..90d4de6 (17 commits) -->

# What's New for Users

- Every user script and gadget in the catalogue now shows a licence. Until now more than ten thousand of them showed nothing at all, which read as though nobody knew — but the answer had been settled all along by the terms everyone agrees to when they publish a page on a Wikimedia project. Those terms place what you write under a Creative Commons licence, and they say nothing to exclude JavaScript. So the licence was never missing, only unwritten, and the catalogue now states it.
- Which version it is depends on when the script was written, and that detail matters more than it sounds. The current terms began on 7 June 2023 and could not reach backwards, so anything published before that date carries the older 3.0 licence and keeps it. Most of this catalogue is older than the change: of the ten most-used scripts on English Wikipedia, every single one predates it. Saying "4.0" across the board would have been the tidier answer and the wrong one for almost everything.
- Where a tool already tells us its licence, that still wins. This fills a blank; it never overrules a maintainer. And where a script was first published on a date we have no record of, it stays blank rather than being given the likelier of the two answers — a good guess is still a guess, and this is the kind of field people rely on before reusing someone's work.
- The new Data layer page showed "temporarily unavailable" to the first people who opened it, for about half a minute after it went live. Nothing was broken and no data was missing: the page reads a summary of the whole catalogue worked out in advance, and immediately after a release that summary had not been worked out yet. It is now prepared as part of publishing the site, before anyone can arrive.
- One column has been dropped from that page's table. It was headed "AI overridden" and was meant to count the times a language model offered a value and a more trustworthy source won instead. It read zero for every field, and always would have: the model is only ever asked to fill a blank, never to compete with something already there. Three columns remain, and each of them says something.
