<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: descriptions-start-again -->
<!-- Release title: Descriptions Start Again -->
<!-- Source range: 155e75f7..f0b32c65 (1 commit, promoted as one) -->

# Technical and Marketing Notes

- `inference-enrichment` produced nothing for sixteen hours and raised no alert. Every tick was OOMKilled: `pending()` selected `UserScriptPage.body` for the whole window, and 19,390 candidates carrying 260.8M characters peaked at 546.7 MB against a `mem: 512Mi` (536.9 MB) container.
- The lock was the symptom, not the cause. SIGKILL leaves no summary line, no `job_runs` row, and no chance for `job_guard.sh` to run its TERM trap, so the lock directory survived; the next hourly tick took the "already running" branch, which exits 0 by design, and the tick after that reclaimed it at `--stale-after 5400` and died the same way. One hard kill therefore costs exactly two ticks, and `emails: onfailure` can never fire for either.
- The window query no longer carries source at all. `with_source` reads `body` and `fingerprint` together for one wave — the sweep's own wave width, `SOURCE_CHUNK = 50` on the serial path — so the pair stays consistent and a page deleted or shrunk between the two reads is dropped rather than recorded against a revision nobody asked about. Measured on the same 19,515-candidate window: 104.7–107.8 MB peak, roughly 5x headroom, with a wave of six adding 52,538 characters and no measurable RSS.
- `MIN_SOURCE_CHARS` moved from a Python skip over an already-loaded body into the SQL `WHERE`, which also stops pages too short to describe from occupying a window slot on every sweep forever. MySQL's `LENGTH()` counts bytes where SQLite's counts characters, so on MySQL the filter admits marginally more than it should and never wrongly excludes; `with_source` re-checks exactly.
- The same predicate went into `coverage()` in the same commit. Adding it to `pending` alone would have let the published `eligiblePages` denominator drift from the set the sweep actually works through — exactly the drift that function's docstring and its denominator test exist to catch, and the test does catch it.
- Validation: five new tests, including a cost guard that stores two 200,000-character bodies and asserts the window carries zero of them — it fails on the old code with `assert 400000 == 0`. All six broker gates green on the merged tree, `pytest-proxy` in 417s.
