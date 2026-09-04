<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: unable-to-look -->
<!-- Release title: Unable To Look -->
<!-- Source range: 157c237d..67e630d6 (3 commits) -->

# What's New for Users

- The data coverage page and the statistics page could each fail with an error under no particular load. Both serve a summary a background job prepares in advance, and both were also claiming the exclusive right to rebuild that summary every time somebody merely read it. Each web worker is allowed two simultaneous conversations with the database; claiming the rebuild right used one and reading the summary used the other, so a single visitor to either page used everything that worker had, and the next request to reach it waited ten seconds and gave up. Reading now costs one conversation, and the rebuild right is claimed only when there is something to rebuild.
- Nothing about how fresh those pages are has changed. The same job refreshes them on the same schedule, a reader still sees the last stored copy rather than waiting for a rebuild, and when a rebuild is genuinely needed one worker performs it while the others carry on serving what they have.
- Separately, the automated check that scans this project's dependencies for known security problems no longer stops all work when the service it consults is unreachable. That service was down for much of this morning, and because the check could not tell "a problem was found" apart from "nobody answered", every change was blocked regardless of content. It now says clearly when it could not look, and still refuses anything with a real problem.
