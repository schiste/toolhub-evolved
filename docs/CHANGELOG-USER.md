<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: an-error-that-means-an-error -->
<!-- Release title: An Error That Means An Error -->
<!-- Source range: 7f6b97f..4919ed7 (2 commits) -->

# What's New for Users

- A tool whose code had just been analyzed successfully could be recorded as a failed scan, then held back from the next few attempts as if it were broken. The analysis itself was stored and already visible on the tool's page; only the bookkeeping said otherwise. Tools that hit this waited hours for a re-read they did not need, and the delay grew each time it happened.
- The cause was a step that runs after the analysis is safely stored: refreshing the summaries and graph entries built from it. A failure there was being reported as a failure of the whole scan, which are two different problems with opposite remedies -- one needs the repository read again, the other needs nothing at all.
- The two are now counted apart, so the catalogue's own status line means what it says: a scan error is a tool left without fresh data, and a stale summary is named separately, on its own line, with the tool it belongs to. A failure that used to be invisible inside an error count is now something an operator can see and act on.
