<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: wiki-source-last-updated -->
<!-- Release title: When The Code Last Changed -->
<!-- Source range: 98f499d8..5f4529bd (6 commits) -->

# What's New for Users

- Gadgets and user scripts now carry a last-updated date, taken from the last time anybody actually edited their source on the wiki. Until now the catalog could say when one of these was created and nothing more, which sorted a gadget rewritten last month behind one untouched since 2009 and gave a reader no way to tell a maintained script from an abandoned one.
- Sorting by "recently updated" and the date shown on a tool's page both use it, so wiki-hosted tools now take their place in those lists alongside the tools whose dates come from Toolhub itself.
- The date is the newest real revision of the code, not the wiki's internal "last touched" marker -- that one also moves when an unrelated template changes or when somebody saves a page without changing it, and publishing it would have reported tools as freshly updated on days nobody touched them. A gadget made of several files takes the newest edit among them, because editing any one of them is editing the gadget.
- Every entry already in the catalog was dated in one pass, and the date is re-checked on a schedule from then on -- hourly for user scripts, daily for gadgets, across all three wikis this site reads. That matters because a gadget's declaration does not change when its code does: without re-checking, a gadget rewritten today would keep showing the date of whatever last edit happened to alter a declaration.
- Where no date can be established -- code that lives on a wiki this site does not read, or a page the wiki databases cannot answer for -- no date is shown at all, rather than a stand-in that would read as fact.
- This release also carries a change with nothing to see: one of the automated checks that runs over this site's code every week had been failing every week for months, and not because anything was wrong. It was set to demand a perfect result the site has never achieved, so it reported the same failure whatever happened, which is the same as reporting nothing. Meanwhile eighteen files were quietly never being checked at all -- among them four of the largest pages on the site -- and seventeen more had been switched off by two unrelated details in the tests, one of them a stopwatch. The check now asks each area to hold the standard it actually reached, so a failure means something changed for the worse.
