<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: toolhub-digests -->
<!-- Release title: Toolhub Digests -->
<!-- Source range: 0cd2a68..dce248b (50 commits) -->

# What's New for Users

- Toolhub Evolved now publishes concise English daily, weekly, and monthly digests of newly added tools. Daily editions mention every new tool, every edition covers one closed UTC period, and periods without new tools produce no empty edition.
- Each edition appears as a compact, readable local blog entry and RSS item, while the lightweight archive makes issues easy to scan and Meta-Wiki remains the canonical publication archive with stable pages for sharing and long-term discovery.
- Signed-in users can subscribe by Wikimedia email or by delivery to their talk page on a supported Wikimedia wiki. Email subscriptions require confirmation, unsubscribe links are signed, and new subscriptions never backfill older editions.
- LiftWing's public Qwen 3.6 27B model writes the short editorial introduction and highlights from bounded Toolhub facts. Every highlight must retain verbatim supporting evidence—either the full metadata value or a substantial exact excerpt—and an exact unambiguous tool title is safely resolved to its canonical Toolhub id; invalid or unavailable model output falls back to deterministic factual copy instead of inventing claims.
- Publication and delivery are restart-safe and observable: missed non-empty periods are recovered, deliveries retry without duplication, permanent recipient failures suspend only that subscription, and an hourly audit makes stalled publication or fallback generation visible to operators.
- Three explicitly selected historical editions can be published as ordinary website entries to demonstrate the daily, weekly, and monthly formats. They credit LiftWing Qwen transparently and are not sent to Meta, RSS, email subscribers, or talk pages.
- New digest editions identify catalog authors and verified maintainers when known, link each person to the appropriate Toolhub Evolved author or person page, and provide both the official Toolhub record and safe direct-tool link. Unverified, stale, failed, or expired relationships are excluded, and malformed links are omitted without suppressing the edition.
- Sign-in no longer depends on the background people directory finishing its identity lookups, so an overlapping directory refresh cannot turn a successful Toolhub authorization into an internal-server-error page. Tool cards throughout home, search, people profiles, and the community directory now use proven Toolhub and Toolforge relationships to link every known author or maintainer to their stable person page; unresolved or ambiguous catalog labels remain attribution instead of being guessed as an account identity.
