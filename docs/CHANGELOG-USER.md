<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on any push in this range, so these were written by hand and checked against the commits. -->
<!-- Source range: 828438f..369553c (131 commits) -->

# What's New for Users

- Handle-shaped text in tool metadata no longer creates a second public person unless a trusted account or Toolsadmin source corroborates it; those observations stay visible beneath the real stable identity instead.
- An exact person search now presents the stable person first, keeps same-name metadata in an expandable “not safely linked” disclosure, shows each related tool once with all known roles, and separates incidental description mentions from meaningful matches.
- The operator review queue now contains only conflicts that can be acted on with stable identity evidence; repeated free-text names remain visible as evidence clusters without becoming merge suggestions.
- Community search now combines people, official Toolhub accounts, contributors, matching tools, and unresolved name-only attributions in one URL-driven directory instead of asking visitors to choose an account type first.
- Tool-text matches now show real tool cards instead of pulling every person related to every matching tool into the directory.
- Name-only cards now separate unresolved identity from listed, currently verified, and renewal-needed tool relationships.
- Canonical wiki usernames are now reconciled through their immutable Wikimedia identity, so repeated Toolhub author records such as Magnus Manske appear under one public person without requiring that person to sign in to Evolved.
- Toolforge account discovery now uses Wikimedia's immutable global account id and the actual Toolsadmin Toolforge name, allowing valid maintainer evidence to reconcile even when its Toolhub catalog name differs.
- Bounded deployment cleanup now resolves the largest duplicate identity clusters first, so the most visible repetition is removed without waiting for alphabetical background batches.
- The community directory now uses the same search layout and result-card system as the tool catalog, with shareable filters, relevance sorting, real totals, pagination, retry states, and accessible full names.
- Person and safely linked account cards now show distinct maintainer-tool and Toolhub-record-owner totals, including how many relationships are currently verified; name-only evidence is never counted as ownership.
- Public profiles paginate compact related-tool summaries server-side, preventing prolific maintainers from triggering hundreds of simultaneous Toolhub requests.
- Official Toolhub accounts are synchronized completely and safely, retain the last good directory during interrupted refreshes, and link to people only through immutable Toolhub or Wikimedia identifiers.
- Relationship labels now distinguish listed authorship, verified Toolforge maintenance, Toolhub record authority, unverified attribution, and verification that needs renewal, with evidence source and date details.
- Tool actions are labelled as maintainer actions only for a viewer with a verified maintainer relationship or confirmed write authority; other signed-in contributors see neutral contribution actions.
- Interface messages now use Wikimedia-compatible Banana plural syntax and carry translator documentation for newly introduced community-directory text.
- Historical duplicate review-queue entries are consolidated automatically, so an old duplicate cannot stop the people directory cleanup.
- Long reconciliation runs no longer report a false failure when MariaDB has already released their idle coordination connection after the work committed.
- Older author-name links now open a choice page when a name could refer to several people, instead of selecting an arbitrary profile.
- The people directory no longer presents every repeated free-text author or maintainer label as a different person; unresolved attributions stay visible as grouped evidence instead.
- Verified people can now carry stable Toolhub and Wikimedia account identities plus Toolforge and wiki handles, while reviewed links retain the original author or maintainer role.
- Browse people and open a profile for anyone who works on a tool.
- Publish your own profile, and claim the tools you write or maintain by proving it through your listed author name, your Toolforge membership, a URL you control, or a signed toolinfo file.
- Review the claims you have made, and edit or delete your Evolved profile, from Preferences.
- Health scores now appear together with the tool they describe, instead of arriving a moment later or sometimes not at all.
- Pages carry much less data than before, so they open faster — the front page is about a quarter of its previous size.
- Opening a health score still shows the full breakdown of how it was worked out; that part now loads once the page itself is ready.
- Corrections to the published release notes now take effect immediately instead of being masked by a cached compressed copy.
- No visible change: the release notes on this page are now checked automatically, so they cannot fall behind what has shipped.
