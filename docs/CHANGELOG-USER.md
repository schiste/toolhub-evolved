<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: one-page-nobody-can-read -->
<!-- Release title: One Page Nobody Can Read -->
<!-- Source range: a9f935f08..4a5413eca (1 commit) -->

# What's New for Users

- The English Wikipedia check no longer reports a problem that is not one. Every hourly run of the user-script directory ended by saying two pages could not be read, and it had said so for months. It was not two pages and it was not a fault: it was a single list maintained by a bot, rewritten every day, which has grown past the largest response the directory is willing to download and is counted once for each stretch of activity it turns up in. That figure now sits in its own column, so the count of pages that genuinely failed to load is back to reading zero when nothing went wrong -- which is the only state in which anyone notices it changing.
- The check stops re-discovering the same unreadable page. Pages are fetched fifty at a time, and one page too large to send spoils the whole request; the run then had to split the batch in half, and in half again, to work out which of the fifty was at fault -- and it repeated that search from scratch every time the page came round. It now remembers, within a run, which pages it has already proved it cannot fetch, and asks for those on their own. The other forty-nine arrive in one request as they always should have.
- Nothing about the directory's contents changes. The page in question is a bot-generated index, not a user script anyone installs, and it was never going to appear in the directory either way. Every script that was listed before is listed now, with the same information; what changed is only what the directory reports about its own work. The page is still requested once a run, so if it is ever trimmed back under the limit it will be picked up without anyone intervening.
