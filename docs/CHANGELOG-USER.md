<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: lanes-that-went-quiet -->
<!-- Release title: The Lanes That Went Quiet -->
<!-- Source range: bf8b687..3c0cd87 (10 commits) -->

# What's New for Users

- Recent changes had ingested nothing for four and a half days while reporting itself healthy. Twenty tools deleted upstream sat at the head of its queue and answered "not there" on every run, which the lane treated as a failure worth retrying rather than as an answer, so the whole per-run budget went to the same twenty dead names and no live tool was ever reached. A deleted tool now leaves the queue, and the feed is moving again.
- The same lane had also spent 435 runs hunting a position in the upstream feed that it could no longer reach: the feed only grows, so every event arriving mid-scan pushed the row it was looking for further away. The hunt now gives up after a bounded search and rebuilds from a fresh snapshot instead, which is work that finishes.
- Searching the recent-changes feed by a tool's name now finds the list revision that added or removed it. Those revisions name the tools they changed, and that name is often the only place it is written down -- until now, typing it found the tool's own rows and skipped the list that had just added it.
- This project's own tool page said it was a gadget. So would any web application whose code so much as mentions the MediaWiki JavaScript API, because the type was being guessed from the text of the code. It is no longer guessed: a gadget is a page a wiki serves and a user script is a subpage of a user, and the page a tool lives on now decides which -- or that it is neither.
- Several background jobs now say what actually happened instead of only how much. A maintainer pass that resolves nobody distinguishes tools with no page from pages that list nobody from names that could not be matched to an account; a job that ran out of a shared request budget says which host it spent it at; and a job that loses the race to create a database table now waits for the winner rather than throwing away its whole pass.
