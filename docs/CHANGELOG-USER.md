<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: finishing-what-a-fast-run-starts -->
<!-- Release title: Finishing What A Fast Run Starts -->
<!-- Source range: fec0785d..HEAD -->

# What's New for Users

- A reading pass that gets through a lot of tools now finishes tidily. The last one read 9,338 records — more than three times its predecessor — and then ran out of memory while publishing the results, so it stopped without reporting what it had done.
- Nothing was lost when that happened. Every answer it had paid for was already saved; what died was the step that pushes them onto the site, and the hourly rebuild picks those up anyway. The pages caught up on their own.
- The publishing step now works in slices instead of all at once, so it costs the same memory whether a pass read a hundred tools or ten thousand. That was the only thing standing between the faster reading and a pass that completes.
