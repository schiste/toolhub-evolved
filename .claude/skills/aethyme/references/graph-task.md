# Graph And Task Reference

Read this for graph views, task scope, task packs, and context-pack assembly.
Prefer `explore` first for broad questions; use these commands after you have a
candidate node, symbol, area, or task.

## Table Of Contents

- Repository orientation
- Graph navigation
- Task scope and anchors
- Context packs
- Verification discipline

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

Use relation commands to narrow a known node. Do not run every relation command
for the same node unless each result changes the next step.

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
