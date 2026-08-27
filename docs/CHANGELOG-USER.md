<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: only-what-gets-published -->
<!-- Release title: Only What Gets Published -->
<!-- Source range: f55d94aa..1dfefd7c (3 commits) -->

# What's New for Users

- Most pages on a wiki that look like a user script are somebody's personal copy of someone else's, and this catalogue lists the original rather than every copy. The background workers did not know that: they were writing descriptions, and asking wikis about documentation pages, for all 166,000 of them against a catalogue of about 48,700. They now work from the list of what actually gets published, so the description backlog is a third of what it was and the wikis are asked a third as often.
- Automatically written descriptions were already appearing on tool pages but were missing from the statistics page, which counted only what arrived from official Toolhub. Nearly 2,600 descriptions the site was already showing were invisible in that count. It now measures the catalogue you actually see, so the number moves as the work lands.
- Link checking got roughly twice the coverage without sending more requests. Every wiki tool published the same page twice — once as its page and once as its source view — and each was checked separately. They are now checked once between them, which is what made it affordable to raise the hourly allowance.
- Icons: the queue was spending its whole hourly allowance recording "this tool has no icon", a decision that needs no download at all, so tools with real icons waited behind tens of thousands of tools with none. Those two are now separate, and the backlog that would have taken weeks clears in a morning.
- The people-matching job stopped losing hours to a database lock. It was rewriting unchanged rows every hour for nothing, and those pointless writes collided with the job that runs every minute; on one day that cost 21 hours of matching. Unchanged records are now left alone.
- The background jobs revived last week also do the same work in far less memory: each used to load whole tables to read two or three fields, and now asks for those fields and walks the table in small batches. Nothing about their behaviour changed — this is what stops them running out of memory again as the catalogue grows.
- The extra memory granted to three jobs stays in place for one more release. It comes out once the rewritten jobs have been observed running inside the standard allowance in production, rather than on the assumption that they will.
