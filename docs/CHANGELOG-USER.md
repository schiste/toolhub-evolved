<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-hourly-pass-stops-blocking-everyone-else -->
<!-- Release title: The Hourly Pass Stops Blocking Everyone Else -->
<!-- Source range: 28169925..08371719 (1 commit) -->

# What's New for Users

- The task that works out who wrote and who maintains each tool does one of its jobs by matching tool pages against Wikimedia user pages. Until now it saved that work at the very end of the run, alongside everything else, which meant it sat on the records it had touched for as long as the run lasted — up to twenty-four minutes.
- Anything else that needed one of those records in that window waited, gave up after fifty seconds, and lost whatever it had been doing. Yesterday's release taught the task to start over when that happened to it. This release stops it happening to everybody else.
- That matching step now saves its own work as soon as it is done, so the records are free again in seconds rather than minutes. Nothing about what it decides has changed — only when it lets go.
- One small consequence: a person the run discovers for the first time is matched against Wikimedia on the next hourly pass rather than the same one. In the records we have, that has never actually applied to anybody.
- As with the rest of this week's work, nothing about how you use the site changes. This is the catalogue's authorship keeping itself current without the parts of it getting in each other's way.
