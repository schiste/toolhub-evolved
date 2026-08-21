<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: sources-and-user-scripts -->
<!-- Release title: Tool Sources and User Scripts -->
<!-- Source range: 066225c..5ab372a (64 commits) -->

# Technical Release Notes

- Adds a user-script census: script pages, their load counts, and per-wiki sweep state are persisted, discovered by content model through the MediaWiki API, and swept across frwiki and Meta so cross-wiki demand aggregates onto one record. Copies and per-user configuration pages collapse onto their original, wiki URLs resolve to the page they actually name, and user-space pages are classified before they are counted.
- Projects that census into a ranked directory, exposes it over the read API, and ships the directory page. Zero-demand scripts move to an archive tier rather than being dropped, `owner_of` resolves maintainers by namespace position instead of by title pattern, and a declaring importer can defend a page from the filename rule.
- Reports the external hosts a tool calls and the endpoints it uses, as a first-class `endpoints` bucket in the source-analysis report. Endpoint extraction rejects wiki markup, bare identifiers, assets and manuals, keeps addresses whole, and retains only endpoints rather than every link a tool merely reads.
- Orders source selection by provenance so `MAX_FILES` reads the code a tool is made of before the material describing it: highest source-class weight first, then shallower paths, shared by both the clone scanner and the local CLI. Measured over sixteen repositories this took the corpus from 206 endpoints to 270 and from 318 dependencies to 421.
- Ranks the per-bucket cap on evidence instead of the alphabet — full-precision confidence, then distinct attesting files, then total sightings, then the reading rank of the best evidence file — so a full bucket keeps what a tool's own code said over what its landing pages said.
- Scans tool source that lives on a wiki rather than in a forge: wiki-hosted script and gadget page sets are parsed and enriched through the MediaWiki API into the same repository-metadata table, and the scanner no longer discards what the checkout measured or scores tools on its own clone flags.
- Splits repository enrichment into its own scheduled lane that reads project facts from the source host's API rather than from a clone, with per-host budgets, normalized host timestamps, and outbound fetches that never lend the token to a host it was not issued for.
- Makes archived a terminal repository activity status and links a maintainer's declared successor from the health panel. Also gates frontend diffs in the broker instead of promoting them unrun, and teaches cspell the wiki and forge vocabulary these lanes introduced.
