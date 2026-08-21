<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-worker-that-kept-the-old-code -->
<!-- Release title: The Worker That Kept The Old Code -->
<!-- Source range: 1abf2eb..c713ddd (4 commits) -->

# What's New for Users

- Some of the work behind the catalogue happens in background workers that run continuously -- the one that reads tool repositories, for instance. Updating the site restarted the website itself but left those workers running the version of the code they had started with, so a fix could be released and still not reach the part of the system it was written for. That is what happened to the summary fix in the last release: it was live on the site and absent from the worker for twenty minutes, until it was restarted by hand.
- Updates now restart those workers as part of the release. The jobs that run on a schedule were never affected, because each run starts fresh and picks up whatever is current -- which is exactly why the gap was easy to miss, with most of the system behaving correctly.
- Separately, a set of automated checks covering the release tooling itself turned out not to be running anywhere. They passed whenever someone ran them by hand, so they looked healthy, but nothing ran them automatically and nothing would have been stopped had they failed. They now run on every change to that tooling.
