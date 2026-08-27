<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-repository-nobody-can-read -->
<!-- Release title: A Repository Nobody Can Read -->
<!-- Source range: 2904249c..77d147a6 (1 commit) -->

# What's New for Users

- A tool whose source code lives somewhere the site cannot reach now says so plainly, instead of looking like something that failed and might work next time. Sixty-nine tools were in that position: their repository is private, deleted, or has moved somewhere that asks for a password, and the site has no password to give it — by design, since it reads only what any member of the public can read.
- Those tools were being re-checked once a month, forever, to get the same refusal every time. They are now marked as unreadable and left alone, which is the honest answer rather than a permanent maybe.
- The error list gets shorter and more useful. What is left in it is genuinely worth looking at, rather than seventy entries describing a situation nobody can act on.
- If a tool's record is later pointed at a repository anyone can read, it is picked up again automatically on the next pass. Nothing is written off permanently — the mark is attached to the address, not to the tool.
