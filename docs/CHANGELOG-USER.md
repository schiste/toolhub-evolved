<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: permission-it-never-used -->
<!-- Release title: Permission It Never Used -->
<!-- Source range: 157c237d..674eca92 (2 commits) -->

# What's New for Users

- The data coverage page and the statistics page could each fail with an error while under no particular load. Both serve a summary that a background job works out in advance, and both were also claiming the exclusive right to rebuild that summary every time somebody merely read it. The site allows each of its web workers two simultaneous conversations with the database; claiming the rebuild right used one and reading the summary used the other, so a single visitor to either page used up everything that worker had and the next request to reach it waited ten seconds and gave up.
- Reading now costs one conversation instead of two. The right to rebuild is claimed only when there is actually something to rebuild, which is when the stored summary is missing or has gone unrefreshed long enough that the job producing it has evidently stopped.
- Nothing about how fresh those pages are has changed. The same background job refreshes them on the same schedule, a reader still sees the last stored copy rather than waiting for a rebuild, and when a rebuild is genuinely needed only one worker performs it while the others carry on serving what they have.
