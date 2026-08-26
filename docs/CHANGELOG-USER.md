<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-column-sized-for-a-cursor -->
<!-- Release title: A Column Sized for a Cursor -->
<!-- Source range: f6ae78d4..ab3a2c27 (1 commit) -->

# What's New for Users

- The user script directory works again. The previous release made the wiki list fast by working it out once an hour instead of on every page load — but the place it was saved to could not hold it, so saving it failed and took the whole answer down with it. The page returned an error every time.
- The list is about 300 KB across 1,028 wikis, and the space it was being saved into holds 64 KB. That space was sized years ago for short bookmarks, and nothing had needed more until this.
- It now has room, and the saving step has been separated from the answering step. If saving ever fails again the page falls back to working the list out on the spot: slower, but it still opens.
