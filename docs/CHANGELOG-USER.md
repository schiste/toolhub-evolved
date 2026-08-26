<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: reading-only-what-it-needs -->
<!-- Release title: Reading Only What It Needs -->
<!-- Source range: f55d94aa..9a980b2b (1 commit) -->

# What's New for Users

- The three background jobs revived yesterday now do the same work in a fraction of the memory. Each used to pull every record of a table into memory in full, then read two or three fields off it; they now ask the database for those fields and nothing else, and walk the table in small batches instead of holding it all at once.
- You should notice nothing at all. Icon fetching, link checking and facet refreshing behave exactly as they did this morning — the change is entirely in what the jobs load to decide what to work on.
- What it buys is that they stop getting more expensive as the catalogue grows. Yesterday's release bought room; this one removes the reason they needed it. The next time discovery opens to a new set of wikis, these three will not quietly run out of memory again.
- The fix is pinned by tests that watch the actual database queries and fail if any of the three ever starts reading a field it does not use. That is the part that decays silently, so it is the part now under guard.
- The extra memory granted yesterday stays in place for one more release. It comes out once the rewritten jobs have been observed running inside the standard allowance in production, rather than on the assumption that they will.
