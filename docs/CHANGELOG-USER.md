<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-name-on-the-first-edit -->
<!-- Release title: The Name On The First Edit -->
<!-- Source range: c353c729..1483b53d (1 commit) -->

# What's New for Users

- Wiki gadgets now say who wrote them. Until now they said nothing at all: a gadget lives at an address like `MediaWiki:Gadget-HotCat.js`, which names a part of the wiki rather than a person, so there was no name to show and the field was simply left off. The site now credits whoever made the first edit to the gadget's oldest page — the top line of the page history, which every reader of that wiki can already see.
- User scripts are credited to whoever actually wrote them, rather than to whoever's user space they sit in. Those are usually the same person, but not always: on the French Wikipedia they differ for 954 of 14,433 script pages, about one in fifteen. The usual reason is an administrator installing a script into somebody else's user space, and until now that script was credited to the wrong person.
- Where a wiki has withheld the name on a first edit, no author is published. The site does not fall back to a guess in that case; the script or gadget keeps its creation date and appears without an author, which is the honest answer.
- Script names are unchanged. A script is still listed under the page it lives at, so crediting somebody else does not move a script to a new address or change the link you already have.
- Nothing needs to be re-requested. Authors fill in over the next few rounds of the regular wiki check, one batch of pages at a time, alongside the creation dates the site was already collecting.
