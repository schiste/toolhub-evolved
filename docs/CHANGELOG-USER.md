<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: two-locks-and-a-session -->
<!-- Release title: Two Locks And A Session -->
<!-- Source range: f1fdf6e8..4fac9ac1 (2 commits) -->

# What's New for Users

- Two of the site's background jobs had started failing, and they no longer do. Neither is anything a visitor sees directly: one works out which people are behind which tools, the other keeps contributors' real names in step with Phabricator. They had been failing since earlier the same day, and the cause was a change made that morning to stop the site as a whole running out of database connections. That worked -- the site stopped running out -- but the allowance handed to each background job turned out to be one short of what these two need, so they ran out instead.
- The allowance is now measured against what those jobs actually hold rather than what they were assumed to hold. A job that has to wait its turn keeps two claims open at once while it works, not one, and adding the work it does on top of those makes three things in hand where the budget had allowed for two. Nothing about what these jobs do has changed; only what they are permitted while they do it.
- Neither job ever reached the point of being switched off. The site stops a job that fails three times in a row, on the assumption that something is properly wrong with it; each of these had failed once. They run every hour, so the correction lands well before that mattered — but it is worth saying that the safeguard behaved exactly as intended and would have caught this even if nobody had been watching.
