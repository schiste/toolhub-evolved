<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: reading-the-catalogue-faster -->
<!-- Release title: Reading The Catalogue Faster -->
<!-- Source range: 43d97a28..HEAD -->

# Technical and Marketing Notes

- `LIFTWING_CONCURRENCY` 6 to 12, measured rather than guessed. One identical 24-call wave replayed at each width: 6 gave 4.64 calls/s at 1.19s each, 12 gave 7.00/s at 1.53s, 18 gave 7.63/s at 1.75s. Per-call latency climbs with width, so the endpoint queues rather than scaling — 6 to 12 buys 51%, and 12 to 18 buys 9% more for another six sockets against a service shared with the rest of Wikimedia.
- The budget stays at 2400s deliberately, because the deadline is not what binds. The run that spent it whole asked 2,884 times and took 2,522s of wall against the 2,700s timeout — 178s of headroom. Raising the deadline without raising the timeout would simply get runs killed at it, and raising both would spend the margin that currently absorbs a slow wave.
- Concurrency costs no database connections. The pool workers only make the HTTP request; every write stays on the thread that owns the session, which is what makes this a one-word change rather than a rebalance of the 20-connection account budget.
- On the current backlog of 45,047 records this moves the finish from about 20 hours to about 13. It is not a one-off: the same width applies to new discoveries and to every later re-ask, which is the part that outlives this backfill.
- Validation: 141 worker and tooling tests, `jobs.yaml` parses and every guarded command is otherwise unchanged. The next `inference-enrichment` run picks the width up from its job definition; nothing else in the sweep changes.
