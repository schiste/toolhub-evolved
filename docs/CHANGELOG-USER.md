<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: launch-year-annotation -->
<!-- Release title: What Happened in 2021 -->
<!-- Source range: e454a2d2..4dcd3c6d (3 commits, promoted as one) -->

# What's New for Users

- The statistics page now explains its tallest bar. On the charts of catalog records by year, 2021 stands about three times its neighbors -- not because that many tools were written that year, but because Toolhub launched and imported a catalog that already existed. Hover the small marker beside 2021 and it says so.
- The explanation is not hover-only. It is read out as part of the row, so a reader using a screen reader gets the same context rather than an unexplained number.
- Only the date charts are marked. A chart that has no 2021 -- last-updated dates, for instance -- carries no marker, and neither does a category that happens to be named after a year.
- Pages are a little lighter again. About 1.1 KB of styling described interfaces the site no longer has, and it was still being downloaded on every visit. Nothing on screen changes.
