<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: directory-opens-again -->
<!-- Release title: The Directory Opens Again -->
<!-- Source range: a136925d..4078c267 (1 commit) -->

# What's New for Users

- The user script directory page works again. Since discovery expanded to every Wikimedia wiki, opening it showed "The user-script directory could not be read." and nothing else. The page was asking for a summary of every wiki at once, and that request had grown slow enough that the browser gave up waiting before the answer arrived.
- The summary is now assembled in one go rather than wiki by wiki, so it comes back in a fraction of the time and will keep doing so however many wikis are added.
- Opening the directory without naming a wiki now lands on the wiki with the most scripts to show, rather than on whichever wiki happens to come first alphabetically. That had become a tiny project holding a single archived page, so the page opened on an empty table that was easy to mistake for a broken one.
- Asking for the archive tier without naming a wiki now picks a wiki that actually has an archive, instead of choosing one for the "In use" list and then showing you the archive.
