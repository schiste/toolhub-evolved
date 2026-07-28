# Changelog

## 0.2.0 - 2026-07-28

Detailed release notes for the last 24 hours of work, prepared from 54 commits
landed between 2026-07-27 09:51 +0200 and 2026-07-28 08:16 +0200.

### Summary

- Turned Toolhub Evolved from a toggled experiment into the default hybrid
  experience layered beside official Toolhub.
- Added the core hybrid backend foundations: Evolved-local permissions, shared
  provenance metadata, official-first write handling, and public Evolved-only
  moderation controls.
- Rebuilt the recent changes page and improved perceived performance with
  server-side API caching, stale-if-error behavior, progressive enrichment, and
  versioned production assets.
- Added profile developer settings and the first durable "My tools" resolver
  based on Toolforge membership plus per-tool authorship evidence.
- Hardened OAuth, sessions, stored Toolhub grants, proxy reads, LDAP, CSRF, and
  dependency security.

### Hybrid Foundation

- Removed the Evolved feature toggle so the hybrid experience is the normal
  production path, while keeping the compact site notice visible by default and
  dismissible by the user (`60fbda3`).
- Added Evolved-local roles for signed-in users, reviewers, and admins, with a
  single backend policy entrypoint and ownership checks for local writes
  (`70ab4a2`, `19531ea`, `72fdf4c`).
- Standardized local provenance and sync metadata so Evolved records can state
  whether they are official, local drafts, fallbacks, Evolved-owned records, or
  sync errors without replacing live Toolhub data as canonical (`09e274b`,
  `6c88b3f`, `7b152fe`).
- Added the official-first write lifecycle: validate locally, check Evolved
  permissions, attempt the official Toolhub API write when supported, persist
  sync metadata, retain local fallback records when policy allows it, and report
  Toolhub validation errors cleanly (`68a2182`, `8f6327d`, `b3b88ee`).
- Added Evolved-only public data controls, including moderation and review
  status for public local data that Toolhub does not expose (`bb77918`).
- Added shared frontend sync status components for published, saved locally,
  rejected fallback, pending review, retry, and discard states (`c4fa13e`).
- Updated hybrid issue and feature documentation so the docs match the
  production architecture (`b2bc376`).

### Recent Changes And UI Polish

- Reworked `/recent` into a cleaner sortable table with filters and denser
  columns for item, type, tool owner, last updated by, action, review state,
  updated date, and comment (`55099dc`, `b5e6a14`).
- Aligned the recent table layout with the design system so it respects page
  width and no longer stretches awkwardly across the viewport (`2d633e3`).
- Collapsed long recent-change comments to one line by default with an expanded
  row state for reading the full text (`e5efed8`).
- Made the site notice more compact so it remains readable without dominating
  the page (`1c3d0bc`).

### Caching, Loading, And Runtime Performance

- Added immutable cache headers for versioned production assets (`eb6c7f0`).
- Reduced production module load failures by making frontend bootstrapping more
  resilient (`bb246a8`).
- Added a persistent anonymous Toolhub API cache in the local database for safe
  shared GET reads, excluding authenticated/session/write endpoints (`2c7e42c`).
- Added endpoint-aware cache lifecycle behavior with TTLs, stale-if-error
  handling, recent-change invalidation, diagnostic headers, and immediate
  invalidation after successful official writes (`7cce203`).
- Changed page loading behavior so cached data can render immediately while
  fresh Toolhub data is fetched in the background (`1914ba6`).
- Made `/recent` owner enrichment progressive so expensive owner lookups no
  longer block the first useful render (`b04dce6`).
- Documented cache operations and runbook expectations (`27df51c`).

### Profile, Developer Settings, And My Tools

- Added developer settings under the profile area (`de01651`).
- Added the user's tools page and account surfaces for owned tools (`f284ae8`).
- Added the local `tool_author_claims` backend model for per-tool author
  evidence, including verification status, method, evidence URL/payload, expiry,
  and last error (`acffd45`).
- Added UI badges for verified and unverified authorship evidence, including
  Toolforge maintainer, Toolhub write access, signed toolinfo, and display-name
  only matches (`ee672d1`).
- Documented the hybrid authorship policy: verification is per tool and never a
  global identity claim (`f680114`).
- Clarified provenance copy in the My tools UI and refreshed user-facing hybrid
  plan language (`3683a28`, `e2d5960`).
- Added durable My tools discovery from Toolforge membership: the resolver starts
  from the signed-in Toolhub/Wikimedia username, reads Toolforge memberships,
  fetches exact official `toolforge-*` Toolhub records, and applies per-tool
  evidence providers (`29134d2`).
- Updated Toolsadmin maintainer parsing for the current public maintainer table
  shape, and made failed maintainer checks retryable instead of hiding later
  successful verification (`5db9e69`).

### Security, Sessions, OAuth, And Proxy Hardening

- Compared CSRF tokens in constant time and added coverage for CSRF edge cases
  (`c8e5551`).
- Bounded the in-memory write rate-limit table and covered both idle-user and
  active-user pruning paths (`25e1a7a`, `9b38ccf`).
- Required a stable `TOOLHUB_SECRET_KEY` in production so sessions are not signed
  with per-process random keys (`bfb2a47`, `5d54dd0`).
- Pinned OAuth callback URL generation to the configured public base URL instead
  of deriving it from request headers in production (`a04de83`).
- Encrypted stored Toolhub OAuth grants at rest, with legacy plaintext reads
  migrated on access and unreadable grants dropped to force a fresh sign-in
  (`8a37bb4`).
- Added server-side session epochs so sign-out strands previously issued session
  cookies, not just the current browser session (`857645d`).
- Made sign-out POST-only and CSRF-protected (`d4e7bdd`).
- Switched Toolforge membership discovery to encrypted LDAP (`ef6fe48`).
- Rejected parent-directory traversal segments in proxied anonymous API paths
  (`2a346b3`).
- Added anonymous read rate limiting to the API proxy so Evolved cannot become a
  traffic amplifier toward Toolhub (`d64ec17`).

### Dependencies, Tooling, And Quality Gates

- Merged dependency updates for GitHub Actions, commitlint, globals, stylelint,
  and knip (`bc6603f`, `7c2f8bb`, `8c30c49`, `bd60a5b`, `37eae39`, `fd63015`).
- Required `cryptography` 48.0.1 to address the tracked advisory, and cleaned
  remaining high-severity development-chain advisories (`69e17a0`, `1dcf832`).
- Restored and preserved the 100% proxy coverage gate after the security
  hardening work (`994b21a`).

### Operational Notes

- Existing browser sessions may need one fresh Toolhub sign-in because session
  epoch validation and stable production session secrets are now enforced.
- `TOOLHUB_SECRET_KEY` is required in production. `TOOLHUB_TOKEN_KEY` can be set
  independently when operators want encrypted OAuth grants to survive session
  key rotation.
- The My tools resolver is now automated through Toolforge membership and
  per-tool evidence. Manual username aliasing is intentionally not part of the
  production path.
