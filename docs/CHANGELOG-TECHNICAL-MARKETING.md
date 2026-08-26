<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-silent-hour -->
<!-- Release title: The Silent Hour -->
<!-- Source range: 226fa989..491fbf56 (1 commit) -->

# Technical and Marketing Notes

- `catalog-validation`, `tool-assets` and `graph-enrichment` produced no stdout after 2026-08-25 19:06, 19:07 and 20:55 respectively. Each was OOM-killed within seconds of every hourly start at the Toolforge 512Mi default; reproduced as one-off jobs at exit 137 in 11s, 3s and 9s.
- Root cause is whole-entity table loads that predate the catalogue's growth: `catalog_validation.py:40` materializes all of `CatalogToolProjection` to count candidates and slice `[:limit]`, `tool_assets.py:193-194` adds `ToolAssetCache`, and `graph_enrichment.py:251-252,310` does the same with `CanonicalToolCache` and `GraphToolEnrichment`. The all-projects discovery promoted on 2026-08-25 took `catalog-validation`'s candidate pool from 20,302 to 26,655 to 82,911 across two days.
- Memory was isolated as the only variable: the identical `catalog_validation` command at `--mem 2Gi` completed and returned `{"candidates": 82911, "processed": 5, "reachable": 5}`.
- The failure was undetectable by design accident. OOM is SIGKILL, which skips `job_guard.sh`'s `trap cleanup 0`, so no state was written and the three-consecutive-failure breaker never armed — all three state files still read `failure_streak=0 disabled=0 last_exit=0` last modified on Aug 25. SIGKILL also discards block-buffered stdout, since these jobs run without `-u`.
- The only surviving signal was the abandoned `$HOME/.toolhub-job-guard/.<job>.lock` directory and the hourly `job-guard: reclaiming <job> lock abandoned 3600s ago` line on stderr, which reads as routine reclaim rather than a job that has never once exited cleanly.
- `jobs.yaml` now sets `mem: 2Gi` on the three jobs, each with an in-block note recording the measured cause, the date the job went silent, and that deleting the line again is the signal the query fix landed.
- This is deliberately a stopgap. Session 165 fixed the same defect class in `catalog_projection.refresh_candidates` this morning by selecting five scalar columns instead of the entity — the projection row carries four JSON blobs and `search_text`, ~10KB each — and the same treatment is queued for these three as a separate release.
- Validation: `jobs.yaml` parses to 32 jobs; `tests/tools/test_continuous_jobs.py`, `test_job_command_signals.py` and `test_service_template.py` pass (12). Broker gates `pytest-tools` and `prettier` passed on tree `a49748dff378`.
