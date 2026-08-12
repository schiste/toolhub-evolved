<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on any push in this range, so these were written by hand and checked against the commits. -->
<!-- Source range: 828438f..04bfcf1 (139 commits) -->

# What's New for Users

- The Community directory now searches people, official Toolhub accounts, contributors, matching tools, and unresolved name-only evidence together, with shareable filters, useful ranking, pagination, retry states, and accessible cards.
- Stable Toolhub, Wikimedia, wiki, and Toolforge identifiers now bring duplicate catalog records under one public person when the evidence is safe; repeated free-text labels stay grouped and explicitly unresolved instead of becoming fake people.
- Tool relationships now explain whether someone is a listed author, verified Toolforge maintainer, Toolhub record owner, or an unverified or expired attribution, including evidence and verification dates where available.
- Public profiles show each related tool once with every known role and compact paginated summaries; legacy name links disambiguate safely, and maintainer-only actions appear only for people with verified authority.
- Pages and health information load with smaller payloads, bounded background refreshes, stable quick views, and loading states that settle instead of repeatedly remounting the current route.
- Deployment reconciliation, account synchronization, translation checks, and release publication now fail safely while preserving the last known-good public data.
