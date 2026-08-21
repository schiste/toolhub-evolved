<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-page-is-not-a-repository -->
<!-- Release title: A Page Is Not A Repository -->
<!-- Source range: c713ddd..f237913 (7 commits) -->

# What's New for Users

- Sixty-one tools whose code could not be read will now be read. The part of the site that analyses a tool's source was following the link the tool's record gives you -- which is usually a page you would open in a browser, not the address the code itself lives at. For repositories on Wikimedia's own Gerrit, and for any link that pointed at a single file or a subfolder rather than the whole project, that meant the analysis failed even though the code was public and perfectly healthy the entire time.
- Those tools will fill in their health scores, licence details and other source information over the day or so after this release, as each one comes up in the normal rotation. Nothing needs to be done to them by hand.
- Large gadgets are no longer skipped. There was a size limit on a single file that made sense for a code repository, where one oversized file among hundreds is usually a bundled library worth ignoring. A gadget is often one page and nothing else, so the same limit quietly dropped the whole tool instead. LiveRC on the French Wikipedia, one of the larger gadgets anywhere, had never once been read.
- Tools whose code really has been deleted or made private are now checked about once a month instead of once a day. Nearly all of the time set aside for reading source code was going into re-confirming a few hundred addresses it already knew were dead, which left genuine work waiting behind them. Anything that comes back online is still picked up.
- Records pointing at placeholder addresses -- leftovers like "your-project" that were never a real repository -- are now recognised as such instead of being retried indefinitely. Correcting the record upstream is enough to bring the tool back into the queue.
