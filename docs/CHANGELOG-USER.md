<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: user-script-creation-dates -->
<!-- Release title: Real Creation Dates for User Scripts -->
<!-- Source range: 5ab372a..1b72aee (9 commits) -->

# What's New for Users

- The user-script directory now names the right original. When several people keep a copy of the same script, the one the directory credits is the one the wiki says was written first, read from Wikimedia's own database rather than inferred from the order we happened to find the pages in.
- That order was previously decided by search relevance, which has nothing to say about which page came first and need not even be the same between two passes over one wiki. Scripts that were credited to a later copy are corrected on the next sweep.
- A script whose creation date cannot be established no longer outranks one whose date is known. It keeps its place in the list, but it can no longer claim to be the original of a script that predates it by fifteen years.
