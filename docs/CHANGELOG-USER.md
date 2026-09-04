<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: one-keyword-is-not-a-choice -->
<!-- Release title: One Keyword Is Not A Choice -->
<!-- Source range: 3476655e..39ec460f (2 commits) -->

# What's New for Users

- User scripts that arrived with only one keyword now get a few more. A keyword list of one is almost never somebody's decision that one was enough — it is what the script's wiki page happened to mention. The catalogue already had a reading of what these scripts do, taken from their own source code, and it was being held back rather than shown. It is now added to lists that had fewer than two keywords, up to six in total.
- Every keyword added this way is marked. A small dagger sits beside it, saying on hover that it was read off the source code by a language model rather than written by the tool's authors. The keywords a maintainer did supply carry no mark, as before, and a tool that already had two or more keywords is left exactly as it was.
- The mark matters more than the keywords do. These lists feed search and the filters beside it, so an unmarked guess would be indistinguishable from something a maintainer chose — which is why the catalogue had been refusing to add them at all. Adding them and saying where they came from is the trade; adding them silently was not on offer.
