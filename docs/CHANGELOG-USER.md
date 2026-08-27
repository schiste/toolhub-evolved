<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: every-wiki-in-its-own-words -->
<!-- Release title: Every Wiki In Its Own Words -->
<!-- Source range: 280abbf5..15a1165a (1 commit) -->

# What's New for Users

- User scripts on wikis that do not answer in English were never analyzed. A German wiki calls the user area `Benutzer:` and a French one `Utilisateur:`, and when the site asked a wiki for a script's pages it compared the answer against the English spelling it had stored, decided nothing matched, and recorded the script as unreadable. This affected 18,603 scripts across roughly 800 wikis — every wiki except the English ones, Commons, Wikidata and Meta, which happen to answer in English and so were the only places this ever worked. Those scripts are now read normally, and each is listed under the name its own wiki uses, which is the one you can paste into that wiki's search box.
- Nothing needs to be re-requested for this. The scripts that failed are retried on their own schedule and will fill in over the next couple of days as each comes back up for a check.
