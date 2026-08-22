<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-stopped-job-lets-go -->
<!-- Release title: A Stopped Job Lets Go -->
<!-- Source range: f45faf1..e35903f (4 commits) -->

# What's New for Users

- Evolved keeps itself up to date with background jobs that run on a schedule. One of them -- the pass that folds new tool and maintainer changes into the people pages -- was managing about one run in ten, and the other nine were skipped without saying so. Contributor and credit changes could take ten minutes longer than they should have to show up.
- The cause was a lock. Each job takes one so that two copies can never run at the same time, and a job that the platform stopped was leaving its lock behind, which blocked every attempt for the next ten minutes. Jobs now hand the lock back when they are stopped, so the next scheduled run starts on time.
- Nothing was lost while this was going on. Work waits in a queue and is picked up by the next run that gets through, so no page is wrong and nothing needs correcting -- it simply arrived later than it should have.
- Every scheduled job on Evolved shares this machinery, so the same quiet ten-minute gap could have opened up in any of them, not just the one where it was spotted.
