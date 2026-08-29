<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-lost-lock-no-longer-costs-the-hour -->
<!-- Release title: A Lost Lock No Longer Costs the Hour -->
<!-- Source range: 1322cff2..776c3197 (1 commit) -->

# What's New for Users

- The task that keeps track of who wrote and who maintains each tool ran once more after yesterday's fixes and stopped again about three minutes in, this time colliding with a different part of the catalogue than the one that was fixed. Nothing it had done was saved, and nothing tried again until the next hour.
- When two things reach for the same record at the same moment, the database picks one and undoes the other's work completely. The task now notices when it was the one undone and starts over straight away, instead of losing the hour.
- It only starts over when there is time to finish. Each of these tasks has a deadline, and a second attempt costs about what the abandoned one did, so a fresh start is offered only in the first half of that deadline. Any later and the task stops and reports the failure, which is how somebody finds out.
- It starts over once, not repeatedly. Losing the same race twice means something is holding on that a third attempt would not outlast, and saying so is more useful than trying again.
- Nothing about how you use the site changes. This is the same work as yesterday's release: authorship on tool pages staying current on its own, rather than depending on somebody noticing that it had not.
