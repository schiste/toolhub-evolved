<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: half-a-timeout-to-spend -->
<!-- Release title: Half A Timeout To Spend -->
<!-- Source range: b4b47523..fc770c83 (2 commits) -->

# What's New for Users

- One of the background jobs that maps tools back to the feeds they come from can now recover from a database conflict instead of giving up. When several jobs write the same records at once the database picks one to undo, and this job had no way to try again; it simply failed and mailed somebody. It now retries once, within a budget that leaves its own time to finish.
- Getting there needed the job to be given a time limit it had never had. It has run 120 feeds every six hours without any bound on how long that may take, so a run that hung would have hung indefinitely. The limit is fifteen minutes, set against a measured worst case of six and a half, and the job's lock is now released automatically at twice that if a run is ever killed part-way.
- A correction to the previous release notes. They said 179 runs had been lost to database conflicts, with 72 from a single job. That was wrong and overstated it: most of those jobs already retry and recover without ever failing, and the job credited with 72 is one of them — its failure counter never left zero. The accurate statement is that 179 conflicts were recorded, an unknown share of them absorbed silently, and two jobs genuinely lost runs.
