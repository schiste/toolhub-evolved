<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: twenty-connections-thirty-six-wanted -->
<!-- Release title: Twenty Connections, Thirty-Six Wanted -->
<!-- Source range: 71a081fa..d51e91ab (7 commits) -->

# What's New for Users

- Some pages answered with an error during busy spells, and they no longer do. On 2 September 107 requests failed that way, most of them the tool summaries a listing needs and the search results page itself. The cause was not the pages: this site is allowed a fixed number of simultaneous conversations with its database, twenty, and it had been arranged to want as many as thirty-six whenever a page and the site's own background bookkeeping ran at the same moment. The parts that ask have now been given shares that add up to what is granted. Nothing was ever lost when this happened — a request failed and would have worked on a second try — but a page that fails at all is a page that looked broken.
- Asking to see archived tools was slow enough to look stuck, sometimes half a minute, and is now immediate. The counts beside each filter were being worked out from scratch across all 53,271 catalogued tools every time somebody ticked that box, while the same counts for the ordinary view had been prepared in advance for a long time. Now both are prepared the same way, so the wider view costs a reader nothing that the narrower one does not.
- Automated visitors are now asked to skip the pages that only repeat what they have already read. Every tool in the catalogue answers at three addresses — the tool, its edit view, its history — and crawlers were walking all three, which is three times the work for nothing a reader would find new. Most of this site's traffic turns out to be automated, and it competes with readers for exactly the database the first item above is about. Tool pages, the people who maintain them, and the home page all stay open to search engines; only the duplicates and the endless filter combinations are withheld.
