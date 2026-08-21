<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: sources-and-user-scripts -->
<!-- Release title: Tool Sources and User Scripts -->
<!-- Source range: 066225c..5ab372a (64 commits) -->

# What's New for Users

- Toolhub Evolved now has a user-script directory. It sweeps the user scripts published on Wikimedia wikis, records how many people load each one, and presents them as a ranked, browsable list rather than a set of pages you had to already know about. The sweep covers the French Wikipedia and Meta together, so scripts used across more than one wiki are counted once for their real reach instead of appearing as unrelated copies.
- The directory tells copies apart from originals. Personal duplicates and per-user configuration pages are folded onto the script they came from, so a popular script shows one entry with its true audience instead of dozens of near-identical ones. Scripts nobody loads any more are filed in an archive tier: still findable, no longer crowding the active list.
- Script ownership is now read from the page's position in the user namespace rather than guessed from its name, so scripts kept in a subpage or under an unusual title are attributed to the right maintainer. A maintainer can also mark a page as theirs when the naming rule would otherwise misfile it.
- Tool pages now show what a tool actually connects to. The analyzer reports the external services a tool calls and the specific endpoints it uses, so you can see at a glance whether a tool talks to the Wikidata Query Service, a Wikimedia REST API, or something else entirely — and it lists only real addresses, not every link that happened to appear in a README.
- That analysis now reads the parts of a repository that matter. It spends its reading budget on the code a tool is made of before the material that merely describes it, which surfaces integrations that were previously missed entirely in large projects. When a tool names more addresses than a page can show, the ones its own code calls are kept ahead of links copied from its documentation.
- Tools whose source lives on a wiki rather than in a code forge are analyzed too. Gadgets and user scripts kept as wiki pages are read through the MediaWiki API and described with the same detail as tools hosted on GitHub or GitLab.
- Repository details are refreshed from what the code host itself publishes, on its own schedule and separately from the code analysis. Each host is given its own budget, so a slow or rate-limited service no longer delays refreshes for tools hosted elsewhere.
- Archived repositories are now recognised as finished rather than merely quiet, and when a maintainer names a successor project the health panel links to it, so a tool that has moved points you to where it went.
