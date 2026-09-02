<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: two-locks-and-a-session -->
<!-- Release title: Two Locks And A Session -->
<!-- Source range: f1fdf6e8..5fa7b46c (3 commits) -->

# What's New for Users

- Several of the site's background jobs had been failing, and three had stopped running altogether. None is anything a visitor sees directly: they work out which people are behind which tools, keep contributors' real names in step with Phabricator, and reconcile identities across sources. They had been failing since a change made the previous day to stop the site as a whole running out of database connections. That part worked and still does -- more than fifteen thousand requests since, without a single failure -- but the allowance handed to each background job turned out to be one short of what several of them need, so they ran out instead.
- The allowance is now measured against what those jobs actually hold rather than what they were assumed to hold. A job that waits its turn keeps two claims open at once while it works, not one, and the work it does on top of those makes three things in hand where the budget allowed for two. Nothing about what these jobs do has changed; only what they are permitted while they do it. The three that had stopped have been restarted.
- Separately, the site's development dependencies picked up seven published security advisories overnight, none of them in anything that runs in production. Two were already fixed in what was installed and only looked unfixed because a lockfile recorded older versions; the rest are now forced to patched releases. One of them had been pinned to an exact version that a later advisory grew to include, which is the kind of thing that goes unnoticed until something checks.
