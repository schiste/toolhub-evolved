<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-hourly-pass-stops-blocking-everyone-else -->
<!-- Release title: The Hourly Pass Stops Blocking Everyone Else -->
<!-- Source range: 28169925..08371719 (1 commit) -->

# Technical and Marketing Notes

- `wikimedia_user_reconciliation.synchronize` writes `person_identifiers` and ran inside `people_reconcile.run`'s single transaction, so every row lock it took was held until the whole pass committed — 1468s on the 07:43Z pass of 2026-08-29. The previous release covered this phase _losing_ a lock race; it did nothing about the writers losing one to it.
- The entrypoint now runs the phase in a `session_scope` of its own and passes the counts down through a new `user_space_result` parameter on `run()`. The locks are released when that transaction commits, seconds later, instead of at the end of the pass.
- It stays inside the shared advisory lock, because it writes: two passes publishing user-space evidence concurrently is the race that lock exists for. Only the transaction moved, not the mutual exclusion — the remote-batch hoist in an earlier release moved a phase out of the lock, and this deliberately does not.
- Ahead of the pass rather than after it, so `source_attestations.refresh_incremental` still reads the evidence in the run that published it. The trade is one pass of phase-ordering lag on identifiers this run's own discovery creates; the hourly loop converges that out, and `identityMappingsApplied` and `registryPeopleCreated` are 0 on every recorded run.
- The counts are handed down rather than recomputed because `synchronize` is fingerprint-cached: a second call in the same pass returns `cacheHit: 1` and zeros, which would erase the record of what was published. For the same reason the phase is guarded against the retry re-entering `body()`, exactly as `prefetch_remote_batches` already is.
- `user_space_result=None` keeps the inline behaviour for callers whose transaction is short enough that the lock window costs nothing: projection publication, and the tests. No existing caller changed.
- Validation: 127 tests across `test_job_runner.py`, `test_people_reconcile.py`, `test_wikimedia_user_reconciliation.py`, `test_projection_refresh.py` and `test_lock_retry.py`. Two new backend tests pin that a supplied result skips the inline pass and that the default still runs it; the four entrypoint ordering tests now assert the user-space transaction opens and commits before the pass does, and that the phase is still inside the lock. Six broker gates, `pytest-proxy` in 277s.
