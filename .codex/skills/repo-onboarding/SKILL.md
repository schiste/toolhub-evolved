---
name: repo-onboarding
description: Use when starting work in an unfamiliar repository, when the task asks for repo overview, setup, architecture, entrypoints, test commands, or where to begin. Skip for narrow file-scoped edits once the relevant paths are already known.
---

# Repo Onboarding: toolhub-evolved

## When to Use

- Load this skill first when the repository is unfamiliar or the request is broad.
- Recommended when: first task in repo, repo overview, setup or run instructions, architecture or entrypoints, where should I start, broad debugging or feature-localization request.
- Skip when: known file-scoped edit, follow-up inside already identified area, task already localized to concrete files.
- Use `.codex/skills/aethyme/SKILL.md` or `.claude/skills/aethyme/SKILL.md` for Aethyme's short operating contract after orientation; load its `references/` files only when needed.

## Repo Identity

- Kind: `repository`
- Languages: `python, typescript`
- Package manager: `python`
- Key manifests: `package.json, pyproject.toml`

## Workspaces

- `.` (primary; python; manifest `pyproject.toml`; high confidence)
- `.` (supporting; npm; manifest `package.json`; high confidence)

## Start Here

- `install`: `python -m pip install -e .`
- `fast_test`: `python -m pytest`
- `lint`: `npm run lint`

## Supporting Commands

- `python -m pip install -e .` (install; medium confidence from `pyproject.toml`)
  Workspace: `.`
- `pytest` (fast_test; medium confidence from `pyproject.toml`)
- `python -m pytest` (fast_test; medium confidence from `pyproject.toml`)
  Workspace: `.`
- `npm run lint` (lint; high confidence from `package.json`)
  Workspace: `.`
- `ruff check .` (lint; medium confidence from `pyproject.toml`)

## Entrypoints

- `test`: `tests` (conventional test root; medium confidence)

## Additional Entrypoints

- `tests` (directory; role=test; conventional test root; medium confidence)

## Repo Map

- `.github` (automation; automation and CI configuration; high confidence)
- `docs` (docs; documentation area; high confidence)
- `tests` (tests; conventional test directory; high confidence)
- `tools` (tooling; developer tooling or scripts; high confidence)

## Aethyme Recipes

- `aethyme explore --repo "$PWD" --request "<task>" --format answer-json`
  Purpose: Broad repository orientation for a user request
- `aethyme repo inspect "$PWD" --mode brief --json-output`
  Purpose: Quick deterministic repo summary
- `aethyme graph callers "$PWD" "<symbol-or-file>" --json-output`
  Purpose: Trace likely impact before editing

## Generated and Dangerous Paths

- Generated/vendor `.aethyme/generated`: tracked generated or vendored surface; verify ownership before editing
- Sensitive `.aethyme/gates.toml`: repository validation policy; changes affect every broker submission
- Sensitive `.github/workflows`: repository automation; changes can affect publication or shared CI

## Freshness

- Source digest: `cb6347b81a825f9b3fb84bc7fb885c6025b16d1991c9bacda882d5c55dd4b95b`
- Tracked source files: `1747`
- Overrides applied: `False`
- Sections generated: `repo, workspaces, primary_workspace, commands, areas, entrypoints, caution_zones, generated_paths, dangerous_paths, navigation_recipes, summon, freshness`
