<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-write-that-changed-nothing -->
<!-- Release title: The Write That Changed Nothing -->
<!-- Source range: a3e51ef3..efcd266a (2 commits) -->

# What's New for Users

- Several background jobs had been failing intermittently for weeks, and one cause of that is now removed. None is anything a visitor sees: they work out which people are behind which tools, keep contributor names in step with external sources, and re-check evidence as it ages. Between them they had logged 179 encounters with the same underlying problem. An earlier version of this note called those 179 lost runs, and that was wrong: several of those jobs retry the moment a database conflict rolls them back, and recover without ever failing. Two of them had no such retry and did lose runs.
- The cause was a write that changed nothing. Every pass over the evidence records re-saved every field, whether or not anything about it had altered, and confirming that nothing changed is by far the most common outcome — one of these passes runs every minute. Each of those pointless saves briefly locked the record, and the other jobs that needed the same records waited behind them until they gave up. The records are now only saved when something about them has actually changed.
- One visible consequence is worth naming. Each piece of evidence carries a "checked at" time, and because confirming a record no longer writes to it, that time now tells you when the evidence last _changed_ rather than when it was last confirmed. Nothing expires or is hidden on the basis of it — a separate expiry date does that — but where several pieces of evidence support the same fact, the ordering between them can differ from before.
