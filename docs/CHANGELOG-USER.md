<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: permissions-in-plain-sight -->
<!-- Release title: Permissions in Plain Sight -->
<!-- Source range: c55797b..e61d34417 (3 commits) -->

# What's New for Users

- Source analysis now says what a tool asks **your browser** for. Until now the report covered what a tool asks the wiki for — the pages it edits, the OAuth scopes it needs — and said nothing about the clipboard, notifications, your location, the camera or the microphone. Those are permissions only you can grant, at the moment the tool runs, and they are now listed under Browser permissions with the line of code that asks for each one.
- Gadgets and user scripts are covered by the same list. A user script declares what it may reach with `@grant` and `@connect`, and a browser extension declares it in its manifest; both are now read and reported the same way as a call made in ordinary code, so the list reads the same whether a tool lives in a repository or on a wiki page.
- No tool's health grade moved because of this. The new list is shown beside the permission findings rather than folded into the score: the grades were calibrated against wiki permissions alone, and changing a published grade because the directory started looking at something new would report a change in the tool that did not happen.
- A release with malformed notes now stops before anything is deployed. The rule that the notes must be readable was only checked once the deployment was already under way, so a bad file could stop a release with the tool left serving its previous build. It is now checked before the change is pushed at all.
