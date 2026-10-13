---
name: aethyme
description: Use Aethyme's high-level Explore intents, current repository
  analyzers, and code graph for navigation, caller tracing, derived facts,
  dead-code analysis, and task context.
---

# Aethyme Navigation

Use this skill for repository navigation, task localization, caller tracing,
dead-code analysis, graph context, compact task packs, and the repository's
broker and commit policy. Start with this contract; load a reference only if
the first result is insufficient.

## Setup

```bash
AETHYME_BIN="${AETHYME_BIN:-aethyme}"
REPO="$PWD"
```

Important: `python -m src.cli ...` was removed — the Python CLI no longer
exists, so that spelling fails outright. Use the `aethyme` binary for
graph, task, facts, intents, analyze, enhance, and Explore.

## Default Contract

Explore is a navigation aid, not an authority: every result is verified against
source before it is relied on. It is most useful for "where is X" questions;
skip it when a direct read or a tiny grep already answers the task.

1. One call for the common case. It prints the compact projection and the top
   2 verified source spans (at most 80 lines each):

```bash
"$AETHYME_BIN" explore --repo "$REPO" --request "<user request>" --format brief
```

2. When you need the JSON (audit, a deeper follow-up, or more than two spans),
   make one bounded Explore call instead, save it to a temp file, and print
   only the compact projection:

```bash
AETHYME_JSON="$(mktemp -t aethyme-explore.XXXXXX.json)"
"$AETHYME_BIN" explore --repo "$REPO" --request "<user request>" --format answer-json --show-observability --depth 0 > "$AETHYME_JSON"
"$AETHYME_BIN" explore-summary --from "$AETHYME_JSON"
"$AETHYME_BIN" verify-targets --repo "$REPO" --from "$AETHYME_JSON" --max-targets 2 --max-lines 80
```

   Inspect only: `safe_to_use_as_answer`, `trust_policy`, `subsystems`,
   `top_verification_targets`, `verification_steps`, and
   `observability.readiness`.

3. Use the returned spans first. If still unverified, read one missing line range
   at a time. Keep each manual command under about 120 output lines / 20k chars
   and the whole post-Explore source verification under about 200 lines.

4. If `safe_to_use_as_answer=false`, follow `verification_steps` and the top
   subsystem lanes as an investigation plan. Do not run broad `rg`, `rg
   --files`, repository-wide grep, multi-file `sed`, or `rg -C` context dumps
   unless the top targets fail.

5. Escalate deliberately. Prefer one deeper Explore call over several unrelated
   commands. Use `--depth 1/2/3` only when the previous result did not provide
   enough evidence to act.

## Load References Only When Needed

- `references/explore.md`: depth, intent, trust/observability, retry rules.
- `references/graph-task.md`: graph views, task scope, context/prompt packs.
- `references/dead-code.md`: usage-boundary, public API, facts, ambiguity.
- `references/broker.md`: sessions, leases, gates, Git/GitHub coordination,
  publication, advisories, recovery.
- `references/policy.md`: commit format, branch and review practice, generated
  files and overrides, verifying the enhancement.

## When Not To Use Aethyme

- A simple file read, exact path lookup, or tiny grep already answers the task.
- You already have one decisive Aethyme result and only need narrow source
  verification.
- The task asks for eval baselines, prior reports, or generated reference
  artifacts as evidence; those must not be used for benchmark answers.
