<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on any push in this range, so these were written by hand and checked against the commits. -->
<!-- Release id: community-directory-identities -->
<!-- Release title: Community directory and connected identities -->
<!-- Source range: 828438f..17037e4 (198 commits) -->

# What's New for Users

- The Community directory now searches people, official Toolhub accounts, contributors, matching tools, and unresolved name-only evidence together, with shareable filters, useful ranking, pagination, retry states, and accessible cards.
- Stable Toolhub, Wikimedia, wiki, Toolforge, and verified toolinfo-source evidence now bring duplicate catalog records under one public person when the evidence is safe; multi-author feeds create one relationship per author, while unsupported or conflicting labels stay grouped and explicitly unresolved instead of becoming fake people.
- Connected identities let signed-in users securely reconnect each legacy Toolforge developer account with an SSH-key proof, restoring its current and future tool relationships without uploading a private key or granting catalog write access.
- Public tool relationships now focus on authors and maintainers; verified Toolforge memberships follow strong project aliases even when older Toolhub records lack the usual `toolforge-` prefix, cards show every author through a compact clickable list, and a bold green name remains the sole visual maintainer cue while detailed evidence and internal permissions stay elsewhere.
- Public profiles show each related tool once with every known role and compact paginated summaries; legacy name links disambiguate safely, and maintainer-only actions appear only for people with verified authority.
- Pages and health information load with smaller payloads, bounded background refreshes, stable quick views, and loading states that settle instead of repeatedly remounting the current route.
- Deployment reconciliation, account and catalog synchronization, translation checks, and release publication now fail safely while preserving the last known-good public data; fresh catalog snapshots never mix independently cached pages, tools confirmed absent from a complete official catalog no longer linger in search or people relationships, and maintenance fixes stay inside one named product release instead of appearing as separate versions.
- Registered toolinfo sources now report names that already exist on official Toolhub as skipped rather than failed, so a feed of tools that are all already listed reads as a clean run and background discovery keeps running instead of switching itself off.
