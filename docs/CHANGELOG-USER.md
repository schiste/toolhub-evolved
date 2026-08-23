<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-script-behind-the-name -->
<!-- Release title: The Script Behind The Name -->
<!-- Source range: 20e338a..HEAD (10 commits) -->

# What's New for Users

- Every script in the user-script directory now has an identity of its own, and answers to it. A link you save keeps working after the directory is rebuilt, which it had not: the directory is thrown away and recomputed on every pass, so the numbers in yesterday's links pointed at whatever happened to land in that slot today. Ask for a page that turned out to be a copy and the directory tells you which script it was filed under, and gives you the identity to follow.
- Popularity is now counted by the page a load actually reaches rather than by the string somebody typed. Wikis accept several spellings of the same page name -- underscores for spaces, a lowercase first letter, a redirect -- and each spelling used to be counted as demand for a different, mostly imaginary script. The scripts people actually load now show the readers they actually have.
- Loads that cross wikis are resolved the same way. A great many editors keep one global script page on Meta that loads tools from their home wiki, and those loads now land on the pages they name instead of vanishing at the wiki boundary.
- The directory now says how much of a wiki it has actually seen, and says it honestly. A wiki part-way through its first pass reports that, rather than showing a short list that reads as though the wiki simply has few scripts. It also reports when the census was last brought up to date, rather than when the job last ran -- a job that runs every hour and finds nothing to do is not the same as a directory that is current.
- English Wikipedia's gadget definitions are now read alongside French Wikipedia's and Meta's. It declares 113 gadgets, more than either of the others, and a gadget is what a successful user script most often grows into.
- On 23 August the whole census stopped. One page on Meta loaded two spellings of the same gadget, which the database regards as one entry and the code regarded as two; the resulting error took down that wiki's pass, and because English Wikipedia is read last, it never got a turn. The database now decides what counts as a duplicate, and one wiki failing no longer costs the others theirs.
- Passes over a wiki are about three times faster, and repeat passes are much cheaper still. English Wikipedia holds roughly 155,000 script pages and had been walked in slices too small to finish; each pass now covers three times as many pages, and a page that has not been edited since the last pass is recognized as unchanged without being downloaded again.
