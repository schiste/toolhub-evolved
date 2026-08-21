<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: user-script-creation-dates -->
<!-- Release title: Real Creation Dates for User Scripts -->
<!-- Source range: 5ab372a..30f1fa9 (7 commits) -->

# Technical Release Notes

- Sorts the census search by `create_timestamp_asc`. `discovery_rank` is recorded as creation order and the collapse reads it as such, but CirrusSearch defaults to relevance, so the "earliest wins" rule had been settling on search score -- a number that is unrelated to creation order and not required to be stable between passes.
- Adds `backend.wiki_replica` and `backend.userscript_creation_dates`: one query reads every user-space `.js`/`.css` page's oldest revision timestamp from the Wiki Replicas and stamps `user_script_pages.created_at_wiki`, a column that had existed unwritten since the table. The Action API cannot batch this -- `rvdir=newer` is `invalidparammix` past one title, so it is one request per page, about an hour and a half on frwiki against roughly a second on the replica. Only a title and a timestamp are selected; actor ids and edit comments are not.
- Runs the stamp from the census job between the sweep and the projection, reporting whether a replica was reached separately from how many rows were written. No credentials, an unreachable replica, or an unknown wiki writes nothing and raises nothing, so every host that is not Toolforge finishes the census normally.
- Breaks the collapse tie on `created_at_wiki`, falling back to `discovery_rank` only where no date exists. Both are compared as strings, so the fallback is rendered behind a leading 9 and sorts after every real timestamp: a page whose creation date is unknown cannot outrank one whose date is known.
- Restores `npm run spell`, which had been exiting 1 on main since 2bed430, and corrects the API-cost figures in USERSCRIPTS.md, which had been stated over the whole 9,919-page corpus rather than the 2,051 pages the collapse actually sees.
