<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-lock-that-says-somebody-is-there -->
<!-- Release title: A Lock That Says Somebody Is There -->
<!-- Source range: ad3d54f7..HEAD -->

# What's New for Users

- Background work recovers in minutes instead of hours when a run is killed. Each of the catalogue's scheduled jobs takes a lock so two copies never run at once, and a job killed by the platform cannot hand its lock back. Until now the next runs simply skipped, and how long they skipped for depended on how long the job was allowed to take rather than on how often it was meant to run.
- One job was losing a full hour of work to this. The task that refreshes cached pages runs every minute, and a single killed run silenced it for sixty consecutive minutes. The worst case is now five minutes, and most jobs lose nothing at all.
- A running job now says so continuously, rather than being guessed at. It touches its own lock while it works, so a long run is never mistaken for a dead one no matter how long it takes, and a dead one is noticed quickly. Nothing about what the jobs do has changed.
