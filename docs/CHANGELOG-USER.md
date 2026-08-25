<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: route-owned-stylesheets -->
<!-- Release title: Lighter Pages, Route by Route -->
<!-- Source range: 6c9bd3c2..e220d177 (2 commits, promoted as one) -->

# What's New for Users

- Every page is lighter. A quarter of the site's largest stylesheet described pages most visitors never open -- the tool map, the accounts directory, the styleguide -- and every page was downloading all of it before it could draw. Those rules now arrive with the page that needs them, which takes about 2.4 KB off every single visit.
- Pages that need their own styling still get it without waiting. The site starts fetching a page's stylesheet at the same moment it starts fetching the page's code, rather than one after the other, so the change costs no delay on the pages it moved rules to.
- The recent-changes, statistics and workers pages start earlier still. Those three already began loading their data before the site's code arrived; now they begin loading their appearance then too.
- Nothing looks different. Every affected page was compared pixel by pixel, in a real browser, against the old build -- and one rule that would have quietly changed the accounts directory was found that way and left alone.
