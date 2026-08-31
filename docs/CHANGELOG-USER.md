<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-first-visitor-paid-for-the-snapshot -->
<!-- Release title: The First Visitor Paid For The Snapshot -->
<!-- Source range: 62afe4b..c3eaed0 (1 commit) -->

# What's New for Users

- The new Data layer page showed "temporarily unavailable" to the first people who opened it, for about half a minute after it went live. Nothing was broken and no data was missing. The page reads a summary of the whole catalogue that is worked out in advance, and immediately after a release that summary had not been worked out yet, so the very first visitor was left waiting for a calculation that covers all 57,352 tools. That calculation now happens as part of publishing the site, before anyone can arrive, so the page is ready the moment it exists.
- The report itself is unchanged and is now fast to load. It covers nineteen fields across the whole catalogue and, for each one, splits what is filled in four ways: written by a person, published by the tool about itself, read out of the tool's source code, or written by a language model.
- Two things it shows are worth knowing. Titles, addresses and repository links are almost entirely written by people or published by the tools themselves, and are over ninety per cent complete. Descriptions and keywords are the opposite: most tools never supplied either, and about eighty-five per cent of the descriptions and ninety per cent of the keywords now in the catalogue were written by a language model filling a blank. The page is the first place that has been visible, field by field, rather than implied.
