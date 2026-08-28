<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: nothing-stops-quietly -->
<!-- Release title: Nothing Stops Quietly -->
<!-- Source range: d67d04ec..4c330d9e (1 commit, promoted as one) -->

# What's New for Users

- When a part of the catalogue stops updating, somebody now finds out. Three times this month a background task died on every single attempt and nothing said so: descriptions stopped for sixteen hours, catalogue checks for a day, and the tool crawler for ten days. Each was found by a person happening to look.
- The site already worked out which tasks had gone quiet and showed it on the workers page. The problem was that the page had to be opened for anyone to see it. A new hourly check reads the same thing and sends mail instead, so the answer arrives without anyone asking the question.
- Nothing you see in the catalogue changes. This only shortens how long stale data can sit there before it gets noticed and fixed.
- One gap is left open on purpose: a task that has never run successfully even once stays quiet, because that looks identical to a task that was only just added. It still shows on the workers page.
