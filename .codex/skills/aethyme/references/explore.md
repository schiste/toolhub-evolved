# Explore Reference

Read this when the initial short skill card is not enough to decide which
Explore depth or intent to use.

## Table Of Contents

- Default flow
- Trust and observability
- Progressive Disclosure: `--depth`
- Intent selection
- Retry rules

## Default Flow

Start with one bounded call. Save the full JSON to a temp file, then print a
compact projection for agent-facing inspection:

```bash
AETHYME_JSON="$(mktemp -t aethyme-explore.XXXXXX.json)"
"$AETHYME_BIN" explore --repo "$REPO" --request "<user request>" --format answer-json --show-observability --depth 0 > "$AETHYME_JSON"
"$AETHYME_BIN" explore-summary --from "$AETHYME_JSON"
"$AETHYME_BIN" verify-targets --repo "$REPO" --from "$AETHYME_JSON" --max-targets 2 --max-lines 80
```

Inspect only the printed projection first: `safe_to_use_as_answer`,
`trust_policy`, `subsystems`, `top_verification_targets`,
`verification_steps`, and `observability.readiness`. Keep the full JSON file
for audit/debug or a later `--detail full` comparison; do not dump it into the
conversation by default.

Verify from the bounded source spans first. Read full target files only if
those spans are insufficient. Read only the missing line range from one target
at a time, keep each manual verification command under about 120 output lines /
20k chars, and keep the whole post-Explore source verification under about 200
lines. Do not run broad `rg`, `rg --files`, repository-wide grep, multi-file
`sed`, or `rg -C` context dumps unless the top targets fail.

## Progressive Disclosure: `--depth`

`explore` accepts `--depth N` where `N` is 0..=3. Lower rungs are cheap and
broad; higher rungs are more expensive and specific.

- `--depth 0`: paths + names for many candidates. Discovery.
- `--depth 1`: paths + names + signatures for a shorter list. Triage.
- `--depth 2`: 20-line snippets for the top few. Read the code.
- `--depth 3`: full content + call-graph closure for one anchor. Commit-level
  and the most expensive rung.

Start at 0 unless you already know the symbol. If the user names a precise
symbol, file, or function, skip discovery and use `--depth 2` or `--depth 3` on
that anchor. If the task is vague, start at `--depth 0`.

Escalate one rung at a time. Stop when you have enough to act. If `--depth 1`
returns one clearly correct candidate, jump to a focused `--depth 3` query for
that candidate instead of loading richer context for every candidate.

When NOT to escalate: if `--depth 0` gives one unambiguous candidate and normal
source reading or narrow grep can verify it, do that. Do not call a deeper
engine command as a formality.

The legacy `--detail compact|standard|full` flag still works for callers that
use the old budget vocabulary. When both flags are passed, `--depth` wins.

## Intent Selection

Use the default `task_localization_query` unless the task clearly fits a
specialized intent.

```bash
"$AETHYME_BIN" explore --repo "$REPO" --request "<user request>" --format answer-json --show-observability --depth 0
```

Use `behavior_localization_query` for debugging, workflows, or "which files
implement this behavior" tasks:

```bash
"$AETHYME_BIN" explore --repo "$REPO" --intent behavior_localization_query --request "<user request>" --format answer-json --show-observability --depth 0
```

Use `usage_boundary_query` for dead-code, public API caller audits, or
boundary usage questions:

```bash
"$AETHYME_BIN" explore --repo "$REPO" --intent usage_boundary_query --request "<user request>" --scope "<directory>" --search-root src --search-root tests --format answer-json --show-observability
```

List the intent catalog only when you need to choose among intents:

```bash
aethyme intents --request "<user request>" --format compact-json
```

## Retry Rules

If `degraded_reasons` reports a graph timeout, read
`observability.degradation_guidance` before retrying. For very large
repositories where first-response speed matters more than graph coverage, pass:

```bash
"$AETHYME_BIN" explore --repo "$REPO" --request "<user request>" --format answer-json --show-observability --params '{"graph_query_timeout_ms":500}'
```

Retry with a narrower request when the first result names an area but not a
specific file. Do not retry with a broader request unless the result contains no
usable answer, hints, or verification path.
