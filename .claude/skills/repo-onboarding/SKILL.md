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
- Languages: `python, javascript`
- Package manager: `npm`
- Key manifests: `package.json, pyproject.toml`

## Start Here

- `install`: `npm install`
- `fast_test`: `npm run test:unit`
- `full_test`: `npm run test:e2e`
- `lint`: `npm run lint`

## Supporting Commands

- `npm install` (install; high confidence from `package.json`)
- `python -m pip install -e .` (install; medium confidence from `pyproject.toml`)
- `npm run test:unit` (fast_test; high confidence from `package.json:scripts.test:unit`)
- `pytest` (fast_test; medium confidence from `pyproject.toml`)
- `npm run test:e2e` (full_test; high confidence from `package.json:scripts.test:e2e`)

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

## Freshness

- Source digest: `f3bbd8cad33ec6d2504e959dd1374a6330acbb0860d4c30cdd3c9146737e5dc9`
- Tracked source files: `587`
- Overrides applied: `False`
- Sections generated: `repo, commands, areas, entrypoints, caution_zones, navigation_recipes, summon, freshness`
