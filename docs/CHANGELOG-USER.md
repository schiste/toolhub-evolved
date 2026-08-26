<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: directory-opens-again -->
<!-- Release title: The Directory Opens Again -->
<!-- Source range: a136925d..0f7a1ac4 (2 commits) -->

# What's New for Users

- The user script directory page works again. Since discovery expanded to every Wikimedia wiki, opening it showed "The user-script directory could not be read." and nothing else. The page was asking for a summary of every wiki at once, and that request had grown slow enough that the browser gave up waiting before the answer arrived.
- The summary is now assembled in one go rather than wiki by wiki, so it comes back in a fraction of the time and will keep doing so however many wikis are added.
- Opening the directory without naming a wiki now lands on the wiki with the most scripts to show, rather than on whichever wiki happens to come first alphabetically. That had become a tiny project holding a single archived page, so the page opened on an empty table that was easy to mistake for a broken one.
- Asking for the archive tier without naming a wiki now picks a wiki that actually has an archive, instead of choosing one for the "In use" list and then showing you the archive.
- Deploying this fix uncovered a second one. The step that refreshes the tool catalogue before each release had been reading every stored tool page in full just to check which ones needed rebuilding, and the catalogue had grown large enough that the step ran out of memory and stopped the release. It now reads only the handful of details it needs to make that decision.
