<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: attribution-stops-losing-its-turn -->
<!-- Release title: Attribution Stops Losing Its Turn -->
<!-- Source range: a1f7f053..c59c52e6 (3 commits, promoted as one) -->

# What's New for Users

- Working out who wrote and who maintains each tool had quietly stopped. The hourly task that does it takes about twenty-three minutes, and for most of a day it either crashed partway through or never started at all. Authorship on tool pages, and the queue of authorship conflicts waiting for a moderator, went stale without anything saying so.
- It crashed on a collision with another task over the same row, and the write it died on was one nobody reads: a "still true" timestamp, refreshed every six hours, on a conflict that had not changed. That refresh now happens after the real work is safely saved, in a moment of its own, and losing it costs nothing.
- It failed to start for a different reason. Four related tasks take turns through a single token, and one of them asks for it every minute while the big one asks once an hour. Whoever asks at the instant the token frees gets it, so the frequent one kept winning — eight hours in a row at the worst. Asking now reserves a place in the queue, and the every-minute task steps aside for one minute when it sees somebody waiting.
- The big task also spends its first two minutes fetching from Wikimedia. It now does that before it takes the token rather than after, so it holds up the others for two minutes less each hour.
- When a task couldn't get its turn, the workers page recorded it as a run that succeeded. It was the fourth way a task could stop without anyone finding out, alongside the three fixed in the last release. A skipped turn is now shown as skipped.
- Nothing about how you use the site changes. This is about the catalogue's authorship staying current on its own, rather than depending on somebody noticing it had not.
