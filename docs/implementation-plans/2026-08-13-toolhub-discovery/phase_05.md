# Toolhub Discovery Implementation Plan — Phase 5: Discovery Skill + Validation

> **For Claude:** REQUIRED SUB-SKILL: Use ed3d-plan-and-execute:executing-an-implementation-plan to implement this plan task-by-task.

**Goal:** A shareable `toolhub-discovery` Claude skill that encodes the prior-art-review methodology and delegates all retrieval to the MCP server, plus recorded regression probes.

**Architecture:** Pure documentation deliverables in `skills/toolhub-discovery/` (new directory) — no Python. The skill contains zero HTTP code; if the MCP server is not configured, it instructs the user to add it and stops. Validation is operator-run (prior-art precision has no ground truth; probes pin known clusters).

**Tech Stack:** Markdown; repo CI checks that apply to prose (`prettier --check .`, `npm run spell` / cspell, possibly markdown linting — check `.github/workflows/ci.yml` JS job for which checks touch `*.md`).

**Scope:** Phase 5 of 5 from `docs/design-plans/2026-08-13-toolhub-discovery.md`. Depends on Phase 4 (deployed MCP endpoint for the manual validation steps; file authoring can proceed before deploy).

**Codebase verified:** 2026-08-13 (`skills/` directory confirmed absent; cspell and prettier confirmed CI-enforced).

---

### Task 1: `skills/toolhub-discovery/SKILL.md`

**Files:**
- Create: `skills/toolhub-discovery/SKILL.md`

**Step 1: Create the skill file** with this content (adjust only if the MCP tool names changed during Phase 4):

````markdown
---
name: toolhub-discovery
description: Use when starting (or scoping) a new Wikimedia tool, bot, gadget, or script — searches the Toolhub catalog for existing tools that already do the idea, adjacent tools, and the libraries/data-access patterns similar tools actually use, then writes a prior-art report.
---

# Toolhub Discovery: prior-art review for Wikimedia tool ideas

## Requirements

This skill performs no HTTP itself. It needs the toolhub-evolved MCP server:

```
claude mcp add --transport http toolhub-discovery https://toolhub-evolved.toolforge.org/mcp
```

If the `search_tools` / `facet_tools` MCP tools are not available in this
session, tell the user to run the command above and STOP. Do not substitute
curl, fetch, or any other transport — the server carries the compliance and
caching obligations for upstream Wikimedia traffic.

## When to invoke

- The user describes a greenfield Wikimedia tool/bot/gadget idea.
- The user asks "does something like this already exist?"
- Before writing a design doc for anything that touches Wikimedia APIs.

## Workflow

### 1. Characterize the idea

From the user's description derive, without asking unless truly blocked:

- **Phrasings** (2–4): different vocabularies for the same idea. Toolhub
  descriptions are terse and inconsistent ("cite checker" vs "reference
  verifier" vs "citation hunt"); one phrasing misses tools. Keep each query
  SHORT and distinctive — 2–3 content words. Search scores terms
  independently, so a full sentence dilutes precision: measured against the
  live index, "citation checker" returned 90 tightly relevant hits while
  "check citations for accuracy on wikipedia articles" returned 2,653 with
  unrelated username- and credit-checkers in the top results.
- **Predicted data access**: which APIs it will plausibly touch, chosen from
  the facet vocabulary: `mediawiki-action-api`, `wikibase-api`,
  `wikidata-query-service`, `mediawiki-rest-api`, `toolforge`,
  `commons-upload`; plus likely `technology` (a language detected in source)
  and `tool_type` (declared in the catalog).
- If the description is too thin to predict data access, ask ONE clarifying
  question, then proceed.

### 2. Retrieve, twice, differently

- **Idea similarity** (full catalog): call `search_tools` once per phrasing,
  limit ~10 each. Keep the union.
- **Pattern similarity** (scanned subset): call `list_facet_values` for
  `dependency` (and `wikimedia_api` if unsure what exists), then `facet_tools`
  with the predicted access pattern. Record the `coverage` field.
- Tools appearing in BOTH sets are the strongest signal: they do what the
  user wants, the way the user would build it. Say so explicitly.
- Fetch full records with `get_tool` for the top candidates before judging.

### 3. Write the prior-art report

Three sections, every claim citing a tool name the user can look up on
https://toolhub.wikimedia.org:

1. **Build, reuse, or differentiate** — tools that already do the idea (or
   nearly). Give an honest redundancy call: if the idea exists and is
   maintained, say "consider contributing instead of building." Deprecated or
   stale tools are still prior art: flag their status, never omit them —
   a dead tool that did the idea is evidence about the idea.
2. **Adjacent tools** — partial overlap: could be extended, or define the
   niche the new tool should occupy.
3. **Recommended stack** — libraries ranked by real adoption among
   pattern-similar tools ("N of the M scanned Python tools touching WDQS use
   X"), from `facet_tools`/`list_facet_values` results, not from memory.

### Mandatory caveats

- Facet filters come in two families and the caveat applies to only one:
  **detected** filters (`dependency`, `api`, `technology`) are read from
  scanned source code and cover ONLY tools with a scanned repository;
  **declared** filters (`tool_type`, `keyword`, `wiki`, `license`) come from
  catalog metadata and cover every tool. When a query used a detected
  filter, always restate the returned `coverage` numbers and phrase absences
  as "no *scanned* tool matches", never "no tool does this". Do not attach
  the coverage caveat to a declared-only result — that would understate it.
- `search_tools` covers the full catalog but matches text, not behavior —
  absence there is also not proof of novelty (wiki-internal scripts and
  unregistered tools exist).
- Do not present adoption counts as quality judgments; a widely used library
  is evidence of ecosystem fit, not of being the best choice.
````

**Step 2: Bring the new directory under the prose checks**

The cspell globs in `package.json` (the `spell` script, line 11) cover `*.md`, `docs/**/*.md`, and `proxy/**/*.py` — `skills/**/*.md` is NOT covered. Extend the `spell` script's globs to include `skills/**/*.md` (prettier's CI `--check .` already covers the directory). Then:

Run: `npx prettier --check skills/ && npm run spell`
Expected: clean (add any legitimately unknown words — e.g. `toolhub`, `WDQS` — to the cspell dictionary the way the repo already does; find its dictionary file first).

**Step 3: Commit**

```bash
git add skills/toolhub-discovery/SKILL.md package.json
git commit -m "feat: add toolhub-discovery skill (prior-art review methodology)"
```

---

### Task 2: Regression probes file

**Files:**
- Create: `skills/toolhub-discovery/PROBES.md`

**Step 1: Create** `skills/toolhub-discovery/PROBES.md`:

````markdown
# Retrieval regression probes

Known clusters of overlapping tools. After any change to search ranking,
facet extraction, or the MCP tools, re-run these probes; a probe that stops
retrieving its cluster is a regression, whatever the code coverage says.

How to run: in a Claude session with the toolhub-discovery MCP server
configured, call `search_tools` with the probe query and check the expected
tools appear in the top 10.

| Probe query | Must retrieve | Why |
| --- | --- | --- |
| "link analysis" | linkdata, linkrecnext, findlinkfast | Documented overlapping cluster (the tools describe each other). |

Probe queries are deliberately short: search scores terms independently, so
a long probe would pass or fail for reasons unrelated to what it is pinning.

Add a row whenever a validation run (see SKILL.md) surfaces a
previously-unknown duplicate cluster: those discoveries are exactly the
ground truth this file accumulates.

## Recorded validation runs

| Date | Project probed | Top hits relevant? | Surprises (unknown tools/libs surfaced) |
| --- | --- | --- | --- |
````

**Step 2: Prose checks, commit**

```bash
npx prettier --check skills/ && npm run spell
git add skills/toolhub-discovery/PROBES.md
git commit -m "docs: add retrieval regression probes for discovery"
```

---

### Task 3: README pointer

**Files:**
- Modify: `README.md` — in or near the section documenting the MCP server (added in Phase 4 Task 5), add a short paragraph pointing to `skills/toolhub-discovery/` : what the skill is, that it is installable by copying the directory into `~/.claude/skills/`, and that the MCP server must be configured first.

**Steps:** edit, run `npx prettier --check . && npm run spell` plus the docs-sync check if it covers README, commit `docs: point to the toolhub-discovery skill`.

---

### Task 4: Operator validation run (manual — requires deployed Phase 4)

Not executable by CI; the executing agent should present this as a checklist to the operator and record outcomes in `PROBES.md`:

0. ~~Confirm the deployed instance's User-Agent contact reaches the actual operator.~~ **Resolved 2026-08-13:** Christophe operates the Toolforge deployment and runs the deploys; `christophe@aeptus.com` (`proxy/app.py:40`) is his address, so the UA correctly identifies the operator and the skill's compliance argument holds. Re-check only if operation changes hands.
1. Configure the MCP server in a fresh Claude session (command in SKILL.md).
2. Run the cluster probe from `PROBES.md`; record pass/fail. **Done when** all expected tools retrieved.
3. Run a full prior-art review (via the skill or the server's `prior-art-review` prompt) for two existing operator projects — suggested: `sfedits` (SF-area edit stream bot) and `alex-cite-checker` — pretending each is a new idea. Judge: are the top idea-similarity hits relevant? Did the pattern side recommend a stack consistent with what those projects actually use? Record both rows in the validation table, including any tool or library the operator did not previously know (the surprise-yield success signal from the design's Definition of Done).
4. File follow-up issues for any probe failure or systematic irrelevance (ranking weights, missing facet values, prompt wording).

---

## Phase completion check

- `skills/toolhub-discovery/SKILL.md` and `PROBES.md` exist, pass prettier + cspell, README points to them.
- Skill text contains: the no-fallback rule, both retrieval tracks, the overlap signal, all three report sections, and every mandatory caveat (compare against the design doc's Phase 5 "Done when").
- Validation checklist delivered to the operator; results recorded in `PROBES.md` once the endpoint is deployed.
