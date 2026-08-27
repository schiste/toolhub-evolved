<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-dates-were-always-there -->
<!-- Release title: The Dates Were Always There -->
<!-- Source range: 8f89c124..68daba19 (2 commits, promoted as one) -->

# What's New for Users

- The statistics page said almost every tool in the catalog had no date. It reported 53,189 of 53,190 tools as "Date unavailable" for when they were created and when they were last changed. The catalog knows those dates for more than 52,000 of them, and the page now shows them.
- The same page counted exactly one tool as having a named author. The catalog names authors for 46,714. The author and completeness figures were wrong by the same cause and are corrected by the same change.
- The last-edit dates read from wiki pages, added in a recent release, were among the dates being dropped. They are now visible where they were meant to be, so a user script or gadget shows when its page was actually last touched.
- Nothing was missing from the catalog and nothing needs re-collecting. The data was there the whole time; the page was reading past it. The figures correct themselves the next time the statistics page rebuilds.
