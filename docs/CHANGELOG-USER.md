<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-script-that-read-as-a-blank-page -->
<!-- Release title: The Script That Read As A Blank Page -->
<!-- Source range: 5a08c45e..4eb9805c (1 commit) -->

# What's New for Users

- A reader told us one of their scripts was missing from the user-script directory. The page is on Meta, it is seventeen kilobytes of working JavaScript, and the directory insisted no such script existed.
- The cause was one character. Many user scripts open with a header describing which pages they run on, and that line often ends in a web address with a `*` on the end — a wildcard meaning "any page on this site". Read literally, the slash and star at the end of that address are also how JavaScript opens a comment. Our reader of these pages took it literally, decided the rest of the file was a comment, and saw a blank page where a script was.
- A blank page is not a script, so the directory left it out entirely — not listed, not even filed as a copy of something else. Fixed: the reader now works out which kind of comment came first instead of assuming.
- The pages that were already read this way do not fix themselves, because we only re-read a page after somebody edits it and these are finished scripts nobody is editing. So this release also re-checks the pages we already hold, using the copies we stored rather than asking the wikis again.
- How many scripts this affects we will know when it runs. The header shape that can trigger it appears on about four hundred pages on English Wikipedia and around sixty each on Meta and French Wikipedia, and only some of those lose their whole file to it.
