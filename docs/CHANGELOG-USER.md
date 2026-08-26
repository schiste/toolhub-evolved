<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: every-wiki-at-once -->
<!-- Release title: Every Wiki at Once -->
<!-- Source range: a9922a0b..6a29146e (2 commits) -->

# What's New for Users

- The user script directory now opens on every wiki at once. Until now it chose a wiki for you and showed only that one — which meant that whichever wiki it chose, you were looking at a fraction of what has been catalogued and had no view of the rest. It now ranks the whole census together, so the most-loaded scripts anywhere are the first thing on the page.
- In that view each row names the wiki it comes from and links to it, and the ranking is numbered straight through rather than restarting at 1 for every wiki. Clicking a script still takes you to that script on its own wiki.
- The wiki picker gains an "All wikis" entry at the top, which is where the page now starts. Choosing a single wiki from it returns to that project's own ranking exactly as before, complete with its own coverage dates.
- The summary above the table says what it can honestly say about a thousand wikis at once. Counts of pages and scripts are added up. Dates are not averaged — you are told the oldest, so "read up to" is a floor every wiki meets rather than a middle nobody sits at.
- It also says how much of the roster is still provisional: how many wikis have not finished a first sweep, and how many hold more script pages than one pass can list. Both were already shown for a single wiki; now they are shown as counts for the whole census.
