<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: skills-stability-accessibility -->
<!-- Release title: Skills, Stability, and Accessibility -->
<!-- Source range: 2cfddf01..e99c9f2f (9 commits) -->

# Technical and Marketing Notes

- Added a versioned Toolinfo Evolved catalog schema and dedicated catalog and discovery modules. Skills use stable repository-plus-skill-root identities; scans preserve commit and run evidence, bounded resource manifests, and complete, partial, or failed refresh status while isolating invalid entrypoints.
- Added additive MCP skills and resources operations while preserving existing tool responses. Repository scans now cover multiple and nested skills and their project targets.
- Bounded memory use across the proxy and SPA with managed outbound response and session cleanup, bulk cache expiry, bounded repository candidate scans, and limits on frontend caches, diagnostics, and selection state.
- Improved catalog accessibility and lifecycle handling with better contrast and accessible labels, graph observer teardown, backend cache locks, and request rate limits.
- Added English static-page translation checks and refreshed contributor, internationalization, and runbook guidance alongside wider API, proxy, and unit coverage.
- Updated fast-uri to 3.1.8 and added read-only authorization regression coverage; Git and Prettier now ignore the local broker worktree-size cache.
- Refreshed the checked-in Aethyme graph, normalized missing Wikimedia responses as transport errors, added coverage for the no-response and repository due-order paths, and updated brace-expansion to 5.0.12 to clear npm audit findings.
