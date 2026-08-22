<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-missing-link-is-not-an-ending -->
<!-- Release title: A Missing Link Is Not An Ending -->
<!-- Source range: fb0d89b..bd2452b (1 commit) -->

# What's New for Users

- Evolved keeps its copy of the tool catalog current by reading a feed of recent changes from Toolhub, remembering where it stopped last time. When that feed answered incompletely -- which is what a timed-out connection looks like -- Evolved concluded the feed had ended and that it had lost its place entirely, and responded by re-reading all 4,645 tools from the beginning.
- That full re-read queued every tool for people-page rebuilding, and that queue is worked through 25 tools a minute so it never slows anything else down. One dropped connection could therefore keep the queue full for about three hours, which is time contributor and credit changes spend waiting. It happened five times in a row over the past day.
- Evolved now checks the feed's own count of how many changes exist before it believes it has reached the end. A page claiming to be the last one while reporting thousands of entries still behind it is treated as a failed read, not as bad news: the place-marker is kept, and the next run tries again fifteen minutes later.
- No page was ever wrong because of this. Each of those five re-reads compared the whole catalog against what Evolved already had and found nothing to change, so it was wasted effort rather than incorrect results -- the only cost was the delay to updates queued behind it.
