<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: permission-it-never-used -->
<!-- Release title: Permission It Never Used -->
<!-- Source range: 157c237d..674eca92 (2 commits) -->

# Technical and Marketing Notes

- `catalog_coverage.snapshot` and `catalog_statistics.snapshot` opened an advisory lock and a session in one `with` block and returned the stored payload from inside it. `advisory_lock` holds a connection of its own for the whole block, so serving a cached snapshot cost two connections — exactly `POOL_SIZE_PER_WORKER + POOL_OVERFLOW_PER_WORKER`. One `/v1/coverage/` request starved its own worker and the request behind it waited out `pool_timeout` and returned 500: 10,423ms on 2026-09-02, which is `POOL_TIMEOUT_SECONDS` and not a slow query.
- The lock decides who may rebuild, and the common path is not rebuilding. It is now taken only when the stored snapshot is missing or past `SNAPSHOT_STALE_LIMIT`, with a re-read after acquiring it because whoever held it while this request queued has probably just stored a fresh copy. The stampede protection is unchanged in the case it exists for: the loser of the race still serves stale rather than rebuilding, and a missing snapshot still takes the lock before building one.
- `catalog_statistics` described itself as sharing this contract with `catalog_coverage`, and shared the defect with it. Both move together, which is the point of the shared contract being written down.
- The tests assert the structure rather than the resource, and the first version of them did not. Counting concurrent connections passed with the defect still in place, because `advisory_lock` returns without taking a connection on any dialect but MariaDB — under SQLite the second connection simply does not exist. Three tests now check whether the common path enters the lock at all, whether a missing snapshot still takes it, and the same for statistics; all three were checked against the defect restored in both modules and caught it as `assert 1 == 0`.
- This is the second time in two days that SQLite has hidden a production cost from a test: a no-op `UPDATE` is nearly free there too, which is how the same evidence-write defect survived two earlier fixes. The rule that keeps holding is to assert the shape the code takes rather than the resource it spends, because the resource is only real where the tests do not run.
- Validation: `tests/proxy` and `tests/tools` together, 3,717 passed and 25 skipped. `ruff check`, `ruff format` and `npm run spell` clean over 305 files, graph index regenerated with the pinned 0.4.2 pair.
