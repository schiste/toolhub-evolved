<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: invisible-character-collisions -->
<!-- Release title: Scripts That Differ by Nothing You Can See -->
<!-- Source range: 1b72aee..4afa859 (7 commits) -->

# What's New for Users

- Meta-Wiki's user scripts are being collected again. One page there loads the same script twice, the second time through a link carrying an invisible character copied in with it. The two spellings look identical, and the database agreed they were identical while our code did not, so it rejected the batch and Meta-Wiki finished every pass with no script data stored at all.
- A script reached through one of those invisible characters now counts as the same script. Its popularity was previously split between two entries that no reader could tell apart, which pushed genuinely popular scripts down the list.
- Tools whose source code lives on a wiki page are found again when the address on record carries one of these characters. The address stopped matching any page, so the tool quietly went without any source information rather than reporting a problem.
