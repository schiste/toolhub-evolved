<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-page-beside-it -->
<!-- Release title: The Page Beside It -->
<!-- Source range: c53f5a9a..e57d6898 (5 commits) -->

# What's New for Users

- User scripts now link to their documentation. By long wiki convention an author writes what a script does on the page beside it — `User:Lupin/popups` next to `User:Lupin/popups.js` — and that page was already there, just never linked from here. The catalogue now asks each wiki whether the page exists and publishes the link when it does, following a redirect when the author moved the documentation somewhere else.
- No link is invented. A script whose author never wrote that page still shows nothing, which stays the rule in this lane: a documentation link is something a reader clicks, so a link to the wrong place is worse than no link.
- Fields the catalogue worked out for itself now carry a small dagger. A user script's documentation link and a gadget's list of technologies were never published by a maintainer — they were read off the wiki here. The mark says so, and says where the value came from, without changing the value beside it. Anything a maintainer actually published stays unmarked, which is most of what you see.
- Tens of thousands of user scripts have no description anywhere, and no amount of further reading of wiki pages will produce one, because nobody ever wrote it down. For those, the catalogue now reads the script's own source code through Wikimedia's Lift Wing service and records a short description and a few keywords.
- That reading can only fill blanks. It is structurally unable to replace anything a person wrote, anything official Toolhub holds, or anything a maintainer's toolinfo.json says — not by convention, but because the code sorts it last and gives it nothing to overwrite. It also touches only description and keywords; every other field is already known from the wiki itself and is left alone.
