<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: what-actually-changed -->
<!-- Release title: What Actually Changed -->
<!-- Source range: 68daba19..fde19fca (1 commit, promoted as one) -->

# What's New for Users

- Recent changes and tool history now show what an edit actually did. Clicking an update opens a comparison of the two revisions, listing each field that changed, what happened to it, and the new value. Until now the history page could only name a revision and send you to the official Toolhub site to find out the rest.
- Every "Updated" entry on the recent changes page is a link to that comparison. Newly created tools are not, because there is no earlier version to compare them against.
- The recent changes page was showing a feed up to a day behind official Toolhub. It was reading a copy that nothing else was requesting, so nothing refreshed it. The page now follows the same copy the rest of the world reads, and the feed keeps up.
- Comparisons are prepared in advance for the changes currently on the recent page, so they open without waiting. An older comparison that was never prepared says it is not available here rather than telling you nothing changed — an edit that genuinely changed no fields is a real answer, and the two now read differently.
