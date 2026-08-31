<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-alarm-that-switched-itself-off -->
<!-- Release title: The Alarm That Switched Itself Off -->
<!-- Source range: 462c5007..59a2b254 (2 commits) -->

# What's New for Users

- The daily summary for 30 August was missing from the archive. It has now been written and published. The single tool it covers, a remote-desktop gadget on English Wikipedia, was registered at 22:01 that night and reached this catalogue at 06:30 the next morning, a quarter of an hour after the day's summary had already been written over a day that still looked empty.
- Nothing was watching it happen. The check that exists to notice a missing summary had been reporting this one since 08:00 that morning, and because it kept reporting a fault it was switched off by the very mechanism that stops a genuinely broken task from retrying forever. A check whose whole job is to fail when something else is wrong can no longer be silenced that way; it now keeps reporting for as long as the problem lasts.
- The deadline it was measuring against was wrong too. It called a summary overdue eight hours after the day ended, while summaries are written once every twenty-four hours, so any tool arriving late in the day produced a complaint nobody could act on for the better part of a day. A day is now only reported as missing its summary once a scheduled writing has actually passed over it. We are not writing summaries more often to close that gap: a published summary never changes afterwards, and writing it earlier in the day would freeze it before the day's late arrivals had landed.
