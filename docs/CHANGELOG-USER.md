<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: not-every-page-is-a-tool -->
<!-- Release title: Not Every Page Is A Tool -->
<!-- Source range: 4395a010..HEAD -->

# What's New for Users

- Gadgets can now have keywords. All 10,882 gadgets in the catalogue had none at all — no wiki writes them down, so there was nothing to copy. They are now read from the description the gadget's own wiki shows on its preferences screen, which about 86% of gadgets have. The description itself is untouched: a maintainer wrote it, and it stays exactly as they wrote it.
- Those keywords come back in English even where the description does not. Most gadget descriptions are written in the wiki's own language, and filters that worked only for English would be filters for English speakers. Each keyword carries the same small dagger as the rest of the catalogue's machine-read metadata, saying on hover where it came from.
- Pages that are not tools no longer pretend to be. About 3,800 catalogued pages are somebody's personal skin file, a copy of a library maintained elsewhere, one tool's saved settings, or a piece of a script that lives on the next page along. Each was being shown a "Listing completeness" scorecard grading it against nine fields and listing everything its author had failed to fill in.
- Those pages now say what they are instead. In place of the scorecard they carry a short line — a personal skin configuration page, a copy of a library maintained elsewhere, and so on. Nothing is hidden or removed: the pages stay in the catalogue, stay searchable, and keep every other panel. Only the checklist goes, because a checklist addressed to nobody cannot be told apart from one addressed to a maintainer who really has neglected their listing.
- A page is treated as a real tool unless there is reason to think otherwise. Filenames that mean the same thing on every wiki decide on their own; everything else waits until the catalogue has tried to read the page and reported that it could not say what it does. A page nobody has looked at yet keeps its checklist.
