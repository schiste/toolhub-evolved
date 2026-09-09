<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-comment-is-not-a-declaration -->
<!-- Release title: A Comment Is Not A Declaration -->
<!-- Source range: 4fe0de81..a905a4c7 (3 commits) -->

# What's New for Users

- A tool is no longer described by words that merely appear near its code. A Go bot for the English Wikipedia had been listed as a Node.js web app that uses a Python library and runs on the Norwegian Wikipedia, all from text the code analyzer had read too literally: a Go module that happens to contain the letters "mwclient", the word "express" in the GPL license, a wikitext tag, and a code comment.
- A library counts only where it can actually be used. A Python library is recognised in Python files, a JavaScript web framework in JavaScript files, and a package manifest in the manifest itself. A name that shows up anywhere else is treated as a mention, not as evidence.
- Running on Node is not the same as being a website. A tool is called a web app when the analyzer sees a web framework in use, not because it runs on a JavaScript runtime that scheduled bots use too.
- Comments and links are read as what they are. A wiki named in a code comment, or linked to as a documentation page, is recorded but only published when a second file agrees, the same bar a README mention already had to clear. License files, and identical copies of a file already read, no longer count as extra opinions.
