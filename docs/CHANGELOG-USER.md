<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-signal-reaches-the-guard -->
<!-- Release title: The Signal Reaches The Guard -->
<!-- Source range: bd2452b..fdbb0d6 (4 commits) -->

# What's New for Users

- Evolved's background jobs each hold a marker while they run, so that two copies of the same job never work at once. A job that is stopped by the platform for running too long is supposed to clear its marker on the way out. It never got the chance: the stop signal was delivered to a wrapper around the job rather than to the job itself, so the job was killed without being asked to stop and its marker stayed behind.
- Every later run of that job then found the marker, assumed a copy was still working, and skipped. The marker is only ignored once it is twice the job's own time limit old, so a single overrun could silence a job for hours -- and the previous release's fix for exactly this problem could not take effect, because the signal was never reaching the code that had been fixed.
- All 29 scheduled jobs now receive the stop signal directly. A job asked to stop clears its marker and the next run starts on schedule, which was verified on the real platform rather than only in tests.
- The job that matches contributors to their accounts had quietly outgrown its half-hour limit: recent runs were finishing with about twenty seconds to spare, and two runs yesterday were cut off at the deadline. It now has twice the time it currently needs, and reports how that time splits between looking up accounts and scanning the catalog, so the next increase can be aimed at whichever half actually grew.
- Catalog updates no longer queue contributor-page rebuilds for tools that did not change. Re-reading the whole catalog used to queue all 4,501 tools regardless, and that queue is worked at 25 tools a minute, so one full re-read delayed genuine contributor and credit updates by roughly three hours.
