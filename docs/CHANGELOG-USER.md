<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-half-that-was-never-read -->
<!-- Release title: The Half That Was Never Read -->
<!-- Source range: 6a39be4..7f2cb28 (6 commits) -->

# What's New for Users

- Evolved's directory of Wikipedia user scripts now covers English Wikipedia, alongside French Wikipedia and Meta. That matters because English Wikipedia is where the largest population of user scripts is written, so it is where a script someone is about to write most likely already exists under another name.
- Meta's coverage was quietly incomplete. Evolved found its scripts by asking Wikipedia's search index, and that index refuses to page past its ten-thousandth result, so Evolved was reading about 500 of Meta's 25,354 script pages. Nothing it showed you was wrong -- it said plainly that it had only read part of the wiki -- but most of the wiki was simply invisible.
- Evolved now reads the list of pages from the Wikimedia databases directly, which answers the same question exactly and without a limit. It also asks each page what kind of content it holds rather than guessing from the filename, which finds the twenty to sixty pages per wiki that hold JavaScript under a name that does not end in `.js`.
- Wikis too large to read in one go are now read across several runs, each picking up where the last stopped. English Wikipedia's 155,561 script pages take about three days to read the first time, and a few minutes an hour to stay current after that.
- Contributor and credit pages update sooner. When Evolved re-read the full tool catalog and found nothing had changed, it still queued all 4,501 tools for rebuilding, and that queue is worked slowly on purpose -- so an hour of real changes waited behind three hours of confirmed non-changes. It now queues only the records that actually moved.
- Scheduled jobs that hit their time limit now stop cleanly and hand back the lock they were holding, instead of being killed with the lock still held. A held lock made every following run of that job skip itself, so one slow run could silence a task for hours.
