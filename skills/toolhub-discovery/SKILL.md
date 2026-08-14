---
name: toolhub-discovery
description: Use when starting or scoping a new Wikimedia tool, bot, gadget, or user script — checks the Toolhub catalog for tools that already do it, adjacent tools worth extending, and the libraries similar tools actually use, before any code is written.
---

# Toolhub Discovery: check for prior art before building

## What this skill is for

The Wikimedia tool ecosystem duplicates work constantly, and the cause is
rarely that people lack a research method — it is that **nobody thinks to
look**. An LLM asked for a tool makes that worse: it will happily build one
that already exists, and Toolforge is taking on new developers faster than
ever. This skill exists to notice the moment, not to explain the workflow.
The workflow itself lives in the MCP server, so it stays correct for every
client that connects to it.

## Requirements

This skill performs no HTTP itself. It needs the toolhub-evolved MCP server:

```
claude mcp add --transport http toolhub-discovery https://toolhub-evolved.toolforge.org/mcp
```

If the `search_tools` / `facet_tools` tools are not available in this session,
tell the user to run that command and STOP. Do not substitute curl, fetch, or
any other transport: the server carries the User-Agent, caching, and rate-limit
obligations for upstream Wikimedia traffic, and a client that bypasses it is
generating uncredited load against Wikimedia infrastructure.

## When to invoke

- The user describes a Wikimedia tool/bot/gadget/user-script idea, even in
  passing ("I should write something that…").
- The user asks whether something already exists.
- Before writing a design doc or opening a repo for anything touching a
  Wikimedia API.

Err toward invoking. The cost of an unnecessary check is a few seconds; the
cost of skipping it is a rebuilt tool.

## How to run the review

Use the server's `prior-art-review` prompt — it carries the full methodology
(how to phrase queries, which facets to try, how to structure the report) and
is the single source of truth for it. In Claude Code it appears as a slash
command from the toolhub-discovery server; you can also read it via
`prompts/get`.

If for any reason the prompt is unavailable but the tools are, the short
version is: search `search_tools` with **2–4 short, distinctive queries using
different vocabulary**, then use `facet_tools` for the technical pattern the
idea implies, then report in three parts — build/reuse/differentiate, adjacent
tools, recommended stack. Tools that appear in both the text search and the
facet search are the strongest signal.

## Reading the results honestly

These are the judgment calls the tool descriptions cannot make for you.

- **One phrasing is not a search.** Vocabulary in Toolhub is inconsistent, and
  a single query routinely reports an empty field that is not empty. Searching
  `bluesky` returns nothing; `mastodon` returns fediverse tools and
  `cross-post` surfaces a bot that already posts wiki content to social
  platforms — the actual prior art for a Bluesky bot.
- **Absence is weak evidence.** `search_tools` matches text, not behavior, and
  plenty of real tools are unregistered or live only as on-wiki scripts. Say
  "I did not find one", never "there isn't one".
- **Two facet families, one caveat.** `dependency`, `api`, and `technology` are
  detected by scanning source, so they only cover tools with a scanned
  repository — always restate the returned `coverage` numbers and phrase gaps
  as "no _scanned_ tool matches". `tool_type`, `keyword`, `wiki`, `license`,
  `task`, and `audience` come from catalog metadata and cover everything, so do
  not attach the scan caveat to them. `task` and `audience` are filled in for
  only a small minority of tools: use them to narrow, never to conclude
  absence.
- **If search is unavailable, say so and stop that half.** `search_tools` has
  no local fallback by design. Do not substitute facet results and present the
  result as a completed review — an incomplete review that reads as complete
  causes exactly the duplicated work this skill prevents.
- **Deprecated tools are still prior art.** Flag their status; never omit them.
  A dead tool that did the idea is evidence about the idea.
- **Adoption is not quality.** "14 of 20 scanned tools use X" means X fits the
  ecosystem, not that X is the best choice.

## After the review

If prior art exists and is maintained, say so plainly and recommend
contributing over rebuilding. That recommendation is the entire point of the
skill; softening it to be agreeable defeats it.
