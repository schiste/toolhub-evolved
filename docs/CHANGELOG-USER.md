<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: every-wiki-in-its-own-words -->
<!-- Release title: Every Wiki In Its Own Words -->
<!-- Source range: 280abbf5..64fdd17b (1 commit) -->

# What's New for Users

- User scripts on wikis that do not answer in English were never analyzed. A German wiki calls the user area `Benutzer:` and a French one `Utilisateur:`, and when the site asked a wiki for a script's pages it compared the answer against the English spelling it had stored, decided nothing matched, and recorded the script as unreadable. Those scripts are now read normally.
- This was almost every wiki. 18,603 scripts across roughly 800 projects were affected — everywhere except the English wikis, Commons, Wikidata and Meta, which happen to answer in English and so were the only places this ever worked. On the French Wikipedia the site had analyzed nothing at all; the English Wikipedia, meanwhile, had over eight thousand scripts read successfully, which is why the gap went unnoticed for so long.
- Each script is now listed under the name its own wiki uses, rather than an English translation of it. That is the name you can paste into that wiki's search box or hand to a maintainer there, so the pages the site reports are the pages you can actually go and look at.
- Gadgets were never affected and are unchanged. They are fetched a different way, by asking for named pages directly instead of searching for them, so the mismatch that broke user scripts could not arise.
- Nothing needs to be re-requested. The scripts that failed are retried on their own schedule and will fill in over the next couple of days as each comes back up for a check.
