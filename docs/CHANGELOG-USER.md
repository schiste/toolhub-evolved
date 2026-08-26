<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: ten-rows-and-a-full-scan -->
<!-- Release title: Ten Rows and a Full Scan -->
<!-- Source range: 6f7b54a0..532ad723 (1 commit) -->

# What's New for Users

- The user script directory now opens instead of intermittently failing to. Loading the list of wikis took up to 24 seconds, and the page waits for that list before it draws anything, so past a certain point browsers gave up and the page showed "the request failed" over a directory that was entirely fine.
- Almost all of that time went on a single count: how many script pages each wiki has, skipping deleted ones. The database had no quick way to tell which pages were deleted, so it opened all 478,189 of them to check. Ten are deleted.
- The database now keeps that answer to hand, and the wiki list itself is worked out once by the hourly census and then simply handed to visitors, rather than recalculated from scratch inside every page load.
- The list is therefore up to an hour behind the very latest sweep. Each wiki still reports its own three dates — when it was last swept, last checked, and how far into recent changes the reader has got — so how current it is stays visible on the page rather than assumed.
- Coming back to the page a second time now usually transfers nothing at all: the browser asks whether the list has changed and is told it has not.
