<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: replica-gaps-and-cold-start -->
<!-- Release title: Missing Histories and Faster First Paint -->
<!-- Source range: cef880a4..8eba1cef (6 commits, promoted as one) -->

# What's New for Users

- The audit log page works. It had been showing "no audit entries" to everyone, always -- not because there were none, but because the page asked for the feed in a slightly different shape than the one kept ready for it, and it treated the resulting error as an empty answer.
- A tool's revision history now loads for the tools people are actually looking at, and when a history genuinely cannot be read the page says so instead of announcing that the tool has never been edited. Those are different facts and the page used to state the wrong one.
- Pages start drawing sooner on a first visit. The four slowest pages now begin fetching their data while the site's code is still downloading, rather than waiting for it to finish first.
- Pages also download less. Visiting the statistics page no longer pulls down the tool-editing forms and the network graph renderer you never opened -- roughly 59 KB less on that page -- and the site's six stylesheets are now delivered as one smaller file.
- The statistics page keeps its selected lens in the address bar. Pick "wiki user scripts and gadgets" and the link you copy opens on that reading for whoever you send it to, and a reload no longer resets it.
