<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: an-error-that-means-an-error -->
<!-- Release title: An Error That Means An Error -->
<!-- Source range: 7f6b97f..001243d (3 commits) -->

# What's New for Users

- A tool whose code had just been analyzed successfully could be recorded as a failed scan, then held back from the next few attempts as if it were broken. The analysis itself was stored and already visible on the tool's page; only the bookkeeping said otherwise. Tools that hit this waited hours for a re-read they did not need, and the delay grew each time it happened.
- The cause was a step that runs after the analysis is safely stored: refreshing the summaries and graph entries built from it. A failure there was being reported as a failure of the whole scan, which are two different problems with opposite remedies -- one needs the repository read again, the other needs nothing at all.
- The two are now counted apart, so the catalogue's own status line means what it says: a scan error is a tool left without fresh data, and a stale summary is named separately, on its own line, with the tool it belongs to. A failure that used to be invisible inside an error count is now something an operator can see and act on.
- Around eighty tools showed no icon at all, and had been quietly retrying for one. A tool record points at its icon by naming the file's page on Wikimedia Commons -- the page that describes the file, with its licence and history -- which is what the format asks for and what those tools correctly provided. The icon cache was fetching that page, finding a web page where it wanted a picture, and recording a failure it then repeated on a slower and slower schedule. It now follows the page through to the file behind it. Large images are fetched at a size suited to an icon, and the few drawings too big to fetch whole are asked for as a scaled copy rather than given up on.
