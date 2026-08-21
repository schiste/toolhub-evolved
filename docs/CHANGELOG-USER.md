<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: gadgets-as-tools -->
<!-- Release title: Gadgets Join the Directory -->
<!-- Source range: 4afa859..df141b6 (17 commits) -->

# What's New for Users

- Gadgets now appear in the directory as tools in their own right, with their own page, card and search results. A gadget is software a wiki has chosen to deploy to everyone who visits it, and until now none of them were listed anywhere, so the directory was missing an entire category of the things people actually use.
- Each gadget entry says which wiki offers it, what it is written in, and links to both its code and its entry on that wiki's gadget preferences page. Gadgets a wiki hides from preferences are read but deliberately left out of the directory: they are machinery other gadgets load rather than something anyone can switch on.
- Gadget entries have no description yet. MediaWiki keeps a gadget's description on a separate page in the wiki's own language, which we do not read yet, and an entry that says nothing is more useful than one that guesses wrong.
- Entries built this way say the wiki declared them rather than crediting Toolhub, which has never been told these tools exist. Where a fact on a tool page came from is often the reason to trust it, so it is stated rather than assumed.
- The recent-activity feed now explains itself when list activity is missing. While the catalog replica is catching up, changes to lists are withheld rather than shown, and the Lists filter used to come up empty with nothing to distinguish a quiet period from a broken page. It now says so in a line of text.
