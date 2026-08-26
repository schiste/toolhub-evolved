<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: ten-rows-and-a-full-scan -->
<!-- Release title: Ten Rows and a Full Scan -->
<!-- Source range: 6f7b54a0..532ad723 (1 commit) -->

# Technical and Marketing Notes

- `/v1/userscripts/wikis/` was measured at 24.4s and 23.0s in the uWSGI access log, against a 1.4s median. `views/userscripts.js` awaits it before issuing any other request, so that was the page's time-to-first-content and, past the browser's read timeout, the view's `catch` branch — an intermittent hard failure presenting as a slow page.
- One of the endpoint's four aggregates was ~25s of the ~25.5s: `COUNT(id) WHERE deleted_at IS NULL GROUP BY wiki`. `EXPLAIN` reported `type: index`, `Using where` with no `Using index` — `deleted_at` is in no index, so MariaDB fetched all 478,189 rows from a 1.8 GB clustered index to evaluate it. The same GROUP BY without the filter, which an existing index covers, runs in 2.2s. Exactly 10 rows have `deleted_at` set.
- `ix_user_script_pages_wiki_deleted` makes that count covering. `migrate._ensure_catalog_read_indexes` gained a general supersession step and retires the shipped bare `wiki` index — a strict prefix of the new one — but only on a run where the replacement is confirmed present, so a create that does not land cannot leave the table worse than it found it.
- The roster is now precomputed into an `ApiCacheMeta` row, following `catalog_statistics`: `snapshot()` reads one row and serves it past its nominal max age, and `userscript_sweep` calls `refresh()` at the end of any run that covered a wiki. Every table the roster reads is written only by the census lane, so that is the sole moment the answer can change — the refresh is neither late nor speculative.
- The index and the snapshot fix different halves. The index alone leaves every visitor paying ~2.5s for four aggregate scans; the snapshot alone moves a 1.8 GB read onto an hourly job on a database already logging error 1205 across ten jobs (66 in maintainer-backfill, 41 in repository-analysis). Together the endpoint is one primary-key read and the rebuild is a covering scan.
- The endpoint returns `public_json_response(..., max_age=300)`, so the roster now carries an ETag and repeat readers revalidate to 304 rather than refetching the whole document.
- Validation: 3,210 proxy tests, 1,331 frontend tests, ruff check/format, cspell and prettier all pass; broker gates passed on the merged tree in 158s. The roster-cost assertion moved from the endpoint onto `build_roster`, since a regression to per-wiki reads is no longer observable from the outside and would surface only as an hourly job growing to fourteen seconds.
