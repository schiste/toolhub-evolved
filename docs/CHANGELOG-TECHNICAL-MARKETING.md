<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: agent-tooling-migration -->
<!-- Release title: Agent Tooling Migration -->
<!-- Source range: eb22a5b6..cef880a4 (2 commits) -->

# Technical and Marketing Notes

- Aethyme moved 0.2.1 to 0.2.2 and brought an embedded repository schema with it. The new binary refuses every broker command against an un-migrated checkout -- including read-only `broker status` -- until `aethyme upgrade apply` has run, which makes the migration a hard prerequisite rather than an optional cleanup. Failing closed on reads as well as writes is the right call for a coordination tool: answering a lease query from a schema the binary no longer understands is how one agent ends up confidently editing a file another agent holds.
- `aethyme upgrade plan --repo . --json` reported schema 0 to 1, `safe: true`, no blockers, and 24 planned paths. Those paths were archived before applying, because the set included `.aethyme/gates.toml` and `.aethyme/overrides/agents.json` -- the files that decide which gates run and against which directories, and a canonical rewrite of either would have been silent and expensive. In the event the migration wrote only `.aethyme/repository.json` and regenerated the onboarding and act artifacts; gates, overrides, `CLAUDE.md`, `AGENTS.md` and `.gitignore` were left untouched.
- The regenerated onboarding artifacts record the commit they were generated from, so committing them necessarily makes their own freshness stamp stale, and regenerating again dirties the tree -- the artifact can never be self-consistent. It is settled here at one step: the stamp names the parent of the commit that carries it, which is a commit that exists. The first generation named a commit that had been rebased away, which is the failure worth avoiding.
- No application code, dependency, job schedule or served asset is touched by this release. `aethyme deploy verify` certifies the result read-only: eight gates valid and cheap-first, config schema 1, `.gitignore` covering broker runtime state, the agent protocol present in `AGENTS.md` and `CLAUDE.md`, and broker database integrity ok.
