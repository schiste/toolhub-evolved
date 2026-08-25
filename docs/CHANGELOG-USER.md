<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: mutation-shard-floors -->
<!-- Release title: The Check That Checked Nothing -->
<!-- Source range: 98f499d8..d5341dc3 (7 commits) -->

# What's New for Users

- Nothing you can see changed in this release. The catalog, the statistics page, search and every published figure behave exactly as they did before it.
- What changed is one of the automated checks that runs over this site's code every week. Its job is to damage the code on purpose, thousands of small ways at a time, and confirm the tests notice. It is how we know the tests are worth having.
- That check had been failing every week for months, and not because anything was wrong. It was set to demand a perfect result the site has never achieved, so it reported the same failure whatever happened, which is the same as reporting nothing. Meanwhile eighteen files were quietly never being checked at all -- among them four of the largest pages on the site -- and seventeen more had been switched off by two unrelated details in the tests, one of them a stopwatch. The check now asks each area to hold the standard it actually reached, so a failure means something changed for the worse.
- The release is recorded here rather than folded quietly into the next one because every deployment is published in this history. A release that changed nothing visible is worth saying plainly, instead of leaving a gap or attaching the work to somebody else's announcement.
