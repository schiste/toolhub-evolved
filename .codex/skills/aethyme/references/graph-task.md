# Graph And Task Reference

Read this for graph views, task scope, task packs, and context-pack assembly.
Prefer `explore` first for broad questions; use these commands after you have a
candidate node, symbol, area, or task.

## Table Of Contents

- Before you run a graph command (graph store posture)
- Repository orientation
- Graph navigation
- Impact of a change
- Task scope and anchors
- Context packs
- Verification discipline

## Before You Run A Graph Command

**Every `aethyme graph`, `aethyme task`, `aethyme query`, `aethyme facts` and
`aethyme analyze` command below reads a local graph store. If that store is
absent, they all refuse.** Explore is the exception: it works without one.

Graph authority is **disabled by default**. In a repository that has not been
enrolled, every command on this page fails. Check before building a plan on
top of them:

```bash
aethyme graph status --repo "$REPO"
```

- **exit 0** — the store is present and current; the commands below work.
- **exit 1** — the store is missing, stale, or blocked. The printed `next:` line
  names the exact command to run. Do not substitute a different one.
- **`--json`** — always exits 0 and carries `fragments.status`,
  `derived_store.status`, `blockers[]` and `next_action`; branch on those
  fields instead of the exit code when you are parsing.

If it reports that graph authority is disabled, enrollment is a repository
change and not yours to make unprompted — say so and fall back to `explore`,
which needs no store. Never fall back to repo-wide `rg`/`find` merely because
the graph is unavailable; report the posture instead.

## Repository Orientation

Use overview only when the user asks for repo orientation or the initial
Explore answer is too broad:

```bash
aethyme graph overview "$REPO" --json-output
```

## Graph Navigation

Inspect a node and nearby graph context:

```bash
aethyme graph node "$REPO" "<file-or-symbol>" --json-output
aethyme graph expand "$REPO" "<file-or-symbol>" --json-output
```

Caller/callee evidence:

```bash
aethyme graph callers "$REPO" "<function-or-method>" --json-output
aethyme graph callees "$REPO" "<function-or-method>" --json-output
```

`node`, `expand` and the relation commands accept either `--json` or
`--json-output`; the two spellings mean the same thing. A misspelled flag is an
error (exit 2) rather than a silent no-op, so a typo will surface immediately.

`graph callers` and `graph callees` exit **1 with `node not found`** when the
target does not resolve, and exit **0 with `"items": []`** when the node exists
but has no such relation. That distinction tells a misspelled symbol apart from
a genuine empty result — check the exit code, not just the payload.

Look one up when you are unsure of the spelling:

```bash
aethyme query symbol "$REPO" "<name-fragment>"
```

Coverage limits worth knowing before you trust a call graph: method calls and
dynamic dispatch are not extracted, and a bare call whose name is ambiguous in
the repository is deliberately left unresolved rather than guessed. An absent
edge usually means "not resolvable", not "not called".

Use relation commands to narrow a known node. Do not run every relation command
for the same node unless each result changes the next step.

## Impact Of A Change

Before editing, ask what the change reaches — callers, importers, tests and
configs — from a diff:

```bash
aethyme graph impact --repo "$REPO" --revision HEAD --diff <file-or-"text">
```

Add `--mode imports` for an import-level view and `--json` for machine output.
This is the highest-value pre-edit command in the toolset. The report states its
own `status` and `confidence`: when the graph does not match the requested
revision it withholds paths and says so — treat that as "verify manually", not
as "no impact".

## Task Scope And Anchors

Use task commands when the user asks "where should I work?", "what files are in
scope?", or "what should I inspect next?" and the initial Explore answer is not
enough.

```bash
aethyme task anchors --repo "$REPO" --task "<task>" --json-output
aethyme task scope --repo "$REPO" --task "<task>" --json-output
aethyme task next --repo "$REPO" --task "<task>" --json-output
```

Read reasons and risks before expanding scope. A file with a clear reason beats
a larger list with weak evidence.

## Context Packs

Use a pack when you need a compact prompt-ready bundle instead of reading many
files manually.

```bash
aethyme task context --repo "$REPO" --task "<task>" --json-output
aethyme task pack --repo "$REPO" --task "<task>" --json-output
```

Inspect selected files, selected symbols, snippets, and token estimates. If a
pack is too large, narrow the task or anchor before asking for a larger pack.

## Verification Discipline

Graph/task output is a candidate selector, not a substitute for reading code.
After a graph or task command, verify with targeted file reads or symbol grep
against the returned paths. Avoid raw `rg --files`, broad `find`, or
repo-wide grep unless Aethyme returned no usable candidates.

Two ways the graph can quietly disagree with the source you are reading:

1. **The store is stale.** `graph status` is the check; do not infer freshness
   from a successful query.
2. **The extraction is incomplete.** Unresolved edges and absent callers are
   expected in the coverage gaps listed above. Absence of evidence in the graph
   is not evidence of absence in the code.
