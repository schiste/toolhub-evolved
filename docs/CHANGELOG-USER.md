<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-census-that-finishes -->
<!-- Release title: The Census That Finishes -->
<!-- Source range: 1e7b87b..cc8f66a (2 commits) -->

# What's New for Users

- English Wikipedia's user scripts are in the directory: 9,742 of them, 3,232 listed as active and 6,510 as archived. It is by far the largest collection of user scripts anywhere, and none of it appeared here before, because the hourly job that reads it ran out of memory at the same point every time and never got as far as writing anything down.
- That is roughly four times as many user-script tools as the directory held yesterday, and it arrives from a census that had already read 154,963 English Wikipedia pages -- the reading was never the part that was failing.
- A census run that is cut short now keeps the pages it had already read. The directory fills in steadily from wiki to wiki instead of throwing away an hour's work whenever a run does not reach the end.
