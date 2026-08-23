<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: every-script-a-tool -->
<!-- Release title: Every Script a Tool -->
<!-- Source range: bebc3d0..1e7b87b (10 commits) -->

# What's New for Users

- The user scripts living in Wikipedia's user space are now tools in the directory, with an author, a link and their source, the same as anything else you can find here. They have never had catalogue entries because nobody writes a tool description for a personal page.
- A script nobody but its author is known to load is listed too, marked **Archived** rather than left out. "We found nothing" and "nothing is there" are different answers, and the directory now keeps them apart instead of quietly reporting a smaller wiki than the real one.
- Personal stylesheets no longer count as tools. They stay in the census, which describes user space, but a page the wiki itself reads as CSS does not become a catalogue entry.
- A script someone copied and tweaked is now recognized as a version of the one it came from, even when the two were renamed apart. Before, only a byte-for-byte copy counted, so the same script under three names looked like three tools.
- An author loading their own script no longer counts as that script being in demand. It was roughly 40% of the signal, and it made a private draft look as wanted as a script other people install.
- Scripts referenced in German, Dutch or any other language's user namespace, or across wikis with a prefix like `en:`, now resolve to the page they name instead of vanishing.
