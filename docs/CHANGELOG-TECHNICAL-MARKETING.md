<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: finishing-what-a-fast-run-starts -->
<!-- Release title: Finishing What A Fast Run Starts -->
<!-- Source range: fec0785d..HEAD -->

# Technical and Marketing Notes

- `_republish` handed its whole list to `refresh_tool_names` at once. That batches internally, but something it holds is not released between batches, so peak memory tracks the list rather than a batch: measured at 281 MiB for 3,000 tools against a 512 MiB job, and killed outright with exit 137 at 9,500. Sliced at 2,000 the same 9,500 plateau at 260 MiB and finish in 175s.
- Only reachable once a sweep got productive enough to fill it. The 10:41 run on 2026-09-05 converted 9,338 records — 3.1x its predecessor, from composing prompts and widening the wave — and died in the republish that followed. The two changes that made the lane fast are what made this reachable, which is why it appeared the same hour they did.
- Diagnosed rather than guessed, and two hypotheses were wrong first. The pod lived about 2,460s against a 2,700s timeout, so it was not killed at the deadline; and republish is cheap in time, 17 ms/tool, so the tail was not overrunning. Reproducing it took republishing 9,500 tools in a 512 MiB job and reading the exit code.
- Nothing was lost. Answers commit per wave, so every Lift Wing call the run paid for was already stored; what died was the republish and the summary. `catalog-projection` is the standing backstop and had already caught the projections up by the time this was diagnosed.
- The guard's heartbeat contained the damage to one run. The lock outlived its owner, went stale 330s later, and the next hour's run reclaimed it -- which under the old rule, twice each job's timeout, would have cost a second run as well.
- Validation: proxy tests with `inference_enrichment` at 100% statement and branch coverage, including that no slice exceeds `REPUBLISH_SLICE` and that none is dropped. The slicing is verified against production: 9,500 real tools, 260 MiB peak, exit 0.
