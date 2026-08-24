# Dead Code And API Boundary Reference

Read this for dead-code, public API caller audits, usage-boundary questions,
and ambiguous internal/external caller decisions.

## Table Of Contents

- Start with usage-boundary Explore
- Direct analyzer fallback
- Facts commands
- Status interpretation
- Verification discipline

## Start With Usage-Boundary Explore

Use the specialized Explore intent first for boundary usage and public API
caller questions:

```bash
"$AETHYME_BIN" explore --repo "$REPO" --intent usage_boundary_query --request "<user request>" --scope "<directory>" --search-root src --search-root tests --format answer-json --show-observability
```

For PHP scopes, this intent uses the scope-first `analyze-usage-boundary`
engine path and avoids building the full repository graph. If
`safe_to_use_as_answer=false`, use the returned `verification_steps[]` before
declaring a function unused.

## Direct Analyzer Fallback

Use the direct analyzer when the user explicitly asks for the legacy dead-code
shape or when Explore asks you to verify with the analyzer:

```bash
aethyme analyze dead-code --repo "$REPO" --scope "<directory>" --boundary outside-directory --format eval-json --show-observability
```

Use `--roots "<dir1>,<dir2>"` when the repository is large and the task gives
likely search roots.

## Facts Commands

For harder cases, derive public surface first, then inspect one target's usage:

```bash
aethyme facts public-functions --repo "$REPO" --scope "<directory>" --json-output
aethyme facts function-usage --repo "$REPO" --target "<function>" --boundary "<directory>" --json-output
```

## Status Interpretation

- `Unused`: no internal or external code callers found.
- `Ambiguous`: no external code callers found, but internal callers or
  docs/config-only references exist. This may satisfy a boundary prompt but may
  not be safe to remove.
- `Used`: at least one caller exists outside the boundary.

Read `excluded_functions` and ambiguity fields before finalizing. A symbol
excluded for visibility, generated code, or test-only usage should not be
silently promoted into the answer.

## Verification Discipline

Dead-code answers require source-backed evidence. Verify returned definitions,
callers, docs/config references, and boundary classification with targeted
reads or narrow grep. Do not use eval baselines, prior reports, or generated
reference artifacts as evidence for benchmark answers.
