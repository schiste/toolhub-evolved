# Retrieval regression probes

Known clusters of overlapping tools. After any change to search, facet
extraction, or the MCP tools, re-run these; a probe that stops retrieving its
cluster is a regression, whatever the test suite says.

How to run: in a session with the toolhub-discovery MCP server configured,
call `search_tools` with the probe query and check the expected tools appear
in the top 10.

Probe queries are deliberately short, for the same reason the skill tells you
to keep real queries short: search scores terms independently, so a long probe
would pass or fail for reasons unrelated to what it pins.

| Probe query     | Must retrieve                       | Why                                                             |
| --------------- | ----------------------------------- | --------------------------------------------------------------- |
| `link analysis` | linkdata, linkrecnext, findlinkfast | Documented overlapping cluster — the tools describe each other. |

Add a row whenever a validation run surfaces a previously-unknown duplicate
cluster. Those discoveries are the ground truth this file accumulates, and
they are worth more than invented examples.

## Recorded validation runs

Prior-art review has no ground truth — nobody knows the true answer set, which
is the gap the skill fills. So validation measures two things that can be
observed: whether the top hits are relevant (precision, judged by the
operator), and whether anything surfaced that the operator did not already
know (surprise yield, the real success signal).

| Date | Project probed | Top hits relevant? | Surprises (tools/libraries not previously known) |
| ---- | -------------- | ------------------ | ------------------------------------------------ |
