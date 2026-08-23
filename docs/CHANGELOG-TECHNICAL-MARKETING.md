<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-threshold-that-fell-on-the-hour -->
<!-- Release title: The Threshold That Fell On The Hour -->
<!-- Source range: c7d15ae..687bd78 (2 commits) -->

# Technical Release Notes

- Kubernetes signals only PID 1, and the jobs framework composes every command as `/bin/sh -c -- 'exec 1>>NAME.out; exec 2>>NAME.err; <command>'`. Without a leading `exec` that wrapper shell is PID 1, and a shell with no trap installed while waiting on a foreground child does not forward the signal, so the real process learns nothing until the grace period expires and everything is killed outright.
- The previous release put `exec` on all twenty-nine commands in `jobs.yaml` and stopped there. `tools/deploy.sh` builds two more itself, passing them to `toolforge jobs run --command`, and those were still wrapped: confirmed by reading `/proc` inside the running `projection-refresh-deploy` pod, which showed the wrapper at PID 1 and python at PID 6. Both now carry `exec`; every caller passes a script path and flags only, so nothing there still needs a shell.
- `tests/tools/test_job_command_signals.py` previously read `jobs.yaml` alone, which is why it passed while two commands were unfixed. It now reads `tools/*.sh` as well, and asserts a lower bound on what each parser found, because a parser that silently matched nothing would have passed every assertion below it.
- `job_guard.sh` reclaims an abandoned lock when `lock_age >= STALE_AFTER`. A leaked lock is only ever inspected by a run, so its age is always a multiple of the schedule period. Setting `--stale-after` to 3600 on an hourly job put the threshold exactly on the first inspection, leaving jitter to decide: the twenty-four reclaims recorded in `people-identity-reconcile.err` range 3588-3613s, so ten of them would have skipped and waited another silent hour.
- `stale-after == 2 * timeout` is an invariant enforced by `tests/proxy/test_workers.py`, so the two numbers cannot be chosen independently. `timeout: 1500` with `--stale-after 3000` is first inspected at 3600s with 600s of margin, and 1500s is still nearly twice the 803s worst completed run.
- The new `test_no_reclaim_threshold_lands_on_the_schedule_it_will_be_measured_against` states the rule for every guarded job rather than pinning this one. It skips periods under 600s, where a missed reclaim costs one short interval and is not worth designing against, and asserts that at least ten jobs were actually checked so the filter cannot quietly empty the test.
