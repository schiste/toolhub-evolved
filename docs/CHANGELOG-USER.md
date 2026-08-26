<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-silent-hour -->
<!-- Release title: The Silent Hour -->
<!-- Source range: 226fa989..491fbf56 (1 commit) -->

# What's New for Users

- Three background jobs had been dead for a day and are running again. Between Tuesday evening and Wednesday afternoon the catalogue stopped fetching tool icons, stopped checking whether tool links still resolve, and stopped refreshing the technology facets you filter by. Nothing on the site said so — pages kept loading, they were just quietly going stale.
- What you should notice: icons appearing again on tools registered since Tuesday, link checks resuming, and the facet filters picking up tools added in the meantime. Nothing that was already published changed or was lost; the jobs only ever add and refresh.
- The cause was the catalogue outgrowing them. Opening user-script and gadget discovery to every Wikimedia project multiplied what these jobs sweep — one of them went from about twenty thousand items to eighty-three thousand in two days — and each ran out of the memory it had been given, mid-run, every hour.
- They failed in the worst way available: killed outright rather than crashing, which left no error to report and no record to trip the automatic disable-and-alert that exists for exactly this. The only trace was a stray line in a log that read like routine housekeeping.
- This release gives them the room they now need. A second release will make them stop needing it, by having them read only the handful of fields they actually use instead of loading every record whole.
