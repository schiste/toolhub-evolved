<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: asking-again-when-the-question-changed -->
<!-- Release title: Asking Again When The Question Changed -->
<!-- Source range: 77b26b1c..HEAD -->

# Technical and Marketing Notes

- `audiences` shipped correct and unreachable. Both windows treat a row as current when `source_fingerprint` still matches the source, which says the wiki has not rewritten it — and says nothing about whether the stored answer covers the fields now being asked for. 36,545 user-script rows and 9,946 gadget rows sat `ready` with no audience, every one of them current, and no sweep would ever have offered them again. The reachable population was ~140 stale scripts an hour plus new discoveries.
- `ToolInference.prompt_version` records which set of questions produced a row, and both windows re-ask anything below the current one. It is bumped when a field is added to `FIELDS_BY_LANE` and never for a wording change: it answers "is this answer missing something", not "could this be phrased better". 0 is every row stored before the column, which is exactly what those rows are.
- Deliberately a version rather than a check for the absent key. `accept()` does not store a field that produced nothing, so "no `audiences` in the payload" is indistinguishable from "asked, and the model correctly found none" — that test would re-ask those rows on every sweep for ever and the backfill would never drain. Recording what was asked separates the two.
- The re-ask sits in its own tier below untried pages and error retries, so 46,491 rows cannot displace a page nobody has ever asked about. A test asserts that ordering directly, because it is the property that makes a backfill of this size safe to leave running.
- This is the second time a projection change has shipped against a population it could not reach — the first was the inferred-keyword floor, which moved exactly one tool. The shape is the same both times: a rule that is correct in isolation, applied to a set whose membership was assumed rather than counted. The check that would have caught both is the same one, asked before shipping rather than after: how many records does this actually reach today?
- Validation: 3,664 proxy tests with `inference_enrichment`, `models` and `db` all at 100% statement and branch coverage; `ruff check`/`format` and cspell clean. The backfill drains at roughly 1,300 records a run against 46,491, so about a day and a half; `coverage()` already reports both lanes separately, which is where to watch it.
