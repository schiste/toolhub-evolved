<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: two-word-searches-and-quiet-jobs -->
<!-- Release title: Two-Word Searches, And Nothing Stops Quietly -->
<!-- Source range: d67d04ec..a1f7f053 (2 commits, promoted separately) -->

# What's New for Users

- Searching the catalogue for more than one word works again. Until now a search only matched if your words appeared side by side, in that order, in the same field — so "Lupin popups" found nothing at all while "Lupin" and "popups" each found plenty. Every word you type is now looked for separately, and a tool has to contain all of them.
- This means an extra word narrows your search rather than widening it. If you get no results, try removing a word rather than adding one. Results are still listed alphabetically, not best-match-first.
- When a part of the catalogue stops updating, somebody now finds out. Three times this month a background task died on every single attempt and nothing said so: descriptions stopped for sixteen hours, catalogue checks for a day, and the tool crawler for ten days. Each was found by a person happening to look.
- The site already worked out which tasks had gone quiet and showed it on the workers page. The problem was that the page had to be opened for anyone to see it. A new hourly check reads the same thing and sends mail instead, so the answer arrives without anyone asking the question.
- One gap is left open on purpose: a task that has never run successfully even once stays quiet, because that looks identical to a task that was only just added. It still shows on the workers page.
