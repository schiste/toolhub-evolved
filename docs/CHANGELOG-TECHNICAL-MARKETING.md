<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: nothing-stops-quietly -->
<!-- Release title: Nothing Stops Quietly -->
<!-- Source range: d67d04ec..4c330d9e (1 commit, promoted as one) -->

# Technical and Marketing Notes

- Three jobs died on every tick this month with no automatic signal: `crawler` breaker-tripped for ten days from 2026-08-03, `catalog-validation` OOMKilled for a day from 2026-08-25, `inference-enrichment` OOMKilled for sixteen hours from 2026-08-27. All three were found by hand.
- The common cause is that Toolforge mails on a non-zero exit and on nothing else, and a job has three ways to die without producing one: SIGKILL, which skips `job_guard.sh`'s exit trap so no `job_runs` row is written at all; the guard's overlap skip; and the guard's breaker, the last two exiting 0 by design.
- Detection was never the missing piece. `workers._status` has always classified every declared job against its own period — `LATE_PERIODS = 3`, `STALLED_PERIODS = 10` — and its own comment calls a stalled worker the state that "must be impossible to miss". Its only consumer was the `/workers` page, so the gap was that nothing polled it.
- `job-watchdog` is that poller: hourly, it reads `workers.snapshot()` and exits `EXIT_SWEEP_FAILED` naming every worker that is stalled, failing, or late. Running it more often would not make any verdict arrive sooner, because both thresholds are measured in the watched job's periods rather than the watchdog's.
- It deliberately does not run under `job_guard.sh`. The guard disables a job after three consecutive non-zero exits, and this job exits non-zero exactly when something else is wrong, so a stall lasting three ticks would retire the only thing reporting it — the same shape as the crawler failure it exists to catch. A structural test asserts the `jobs.yaml` command contains no `job_guard.sh`, since the omission reads as an oversight and invites tidying.
- Two deliberate limits, both pinned by tests. `unknown` (never ran) is named in the report but never alarms, because it reads identically for a job deployed a minute ago and one broken since birth; alarming would mail about all 33 jobs after a database restore. And the watchdog records its own run as `EXIT_OK` even while alarming, so a verdict about other jobs cannot mark it permanently unhealthy on `/workers` or hide its own death behind somebody else's.
- Validation: 12 new tests covering each alarm branch, the never-ran hole, the exit-code contract, a recorder failure not swallowing the alarm, and the unguarded-command invariant. All seven broker gates green on the merged tree, `pytest-proxy` in 136s.
