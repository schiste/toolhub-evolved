<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: nothing-left-for-a-retry -->
<!-- Release title: Nothing Left For A Retry -->
<!-- Source range: 0dd60716..d3a38432 (2 commits) -->

# What's New for Users

- The last of the connection errors is gone. The previous release stopped the site running out of simultaneous conversations with its database during ordinary browsing, and that held: over eight hundred requests after it went live, not one of them failed. What it did not cover was a single job that runs every six hours and, while it ran, needed twice what every other job needs. Anyone browsing during those few minutes could still meet an error page.
- That job now does its two halves one after the other instead of at the same time. It reconciles the site's record of who maintains what, it runs four times a day, and nobody is waiting on it while it does, so taking a few seconds longer costs nothing that anybody experiences. In exchange it now asks for no more of the database than any other background job does.
- The site also keeps a small reserve of connections it will not plan to use. That sounds like an odd thing to boast about, but the errors happened without the site ever exceeding what it is allowed: it was using exactly all of it, so the moment anything needed one more — a connection being routinely replaced, or a query being tried again after a hiccup — there was none to give. Planning to use everything and staying inside the limit turn out to be different things, and only the second one survives a bad moment.
