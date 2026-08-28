<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: descriptions-start-again -->
<!-- Release title: Descriptions Start Again -->
<!-- Source range: 155e75f7..f0b32c65 (1 commit, promoted as one) -->

# What's New for Users

- User scripts and gadgets are getting their written descriptions again. Almost none of these tools carry a description on the wiki page they come from, so the catalogue reads the script's own source and writes one. That work had stopped completely for sixteen hours, and no new description had appeared since.
- It stopped because the job that does it ran out of memory every time it started, loading the full text of nineteen thousand scripts at once when it only needed a handful at a time. It now reads each script's source at the moment it is about to describe it, and finishes well inside its limits.
- Nothing already written was affected, and nothing is described twice: a script whose source has not changed keeps the description it already has.
- Scripts too short to say anything meaningful about no longer take up a place in the queue on every pass, so the run spends its time on tools that can actually get a description.
