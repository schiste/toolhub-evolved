<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-comment-is-not-a-declaration -->
<!-- Release title: A Comment Is Not A Declaration -->
<!-- Source range: d169b7a6..7854dd806 (12 commits) -->

# What's New for Users

- A tool is no longer described by words that merely appear near its code. A Go bot for the English Wikipedia had been listed as a Node.js web app that uses a Python library and runs on the Norwegian Wikipedia, all from text the code analyzer had read too literally: a Go module that happens to contain the letters "mwclient", the word "express" in the GPL license, a wikitext tag, and a code comment.
- A library counts only where it can actually be used. A Python library is recognised in Python files, a JavaScript web framework in JavaScript files, and a package manifest in the manifest itself. A name that shows up anywhere else is treated as a mention, not as evidence.
- Running on Node is not the same as being a website. A tool is called a web app when the analyzer sees a web framework in use, not because it runs on a JavaScript runtime that scheduled bots use too.
- Comments and links are read as what they are. A wiki named in a code comment, or linked to as a documentation page, is recorded but only published when a second file agrees, the same bar a README mention already had to clear. License files, and identical copies of a file already read, no longer count as extra opinions.
- Tool pages, people details, and the relationship graph now keep a more consistent picture of the catalog when data is refreshed or edited, with all available catalog metadata—including the projects a skill targets—kept visible.
- Creating and editing a tool now keeps official details and local curation changes coordinated through the same flow, while preserving legacy form data and handling optional annotation fields clearly.
- Catalog views normalize tool information consistently, so the same tool is represented the same way across screens.
- The proxy's environment fallbacks and catalog snapshot paths now meet the project's complete coverage guarantee, keeping refresh failures visible during validation instead of after release; its navigation graph is refreshed alongside those code changes, and authentication failures now return a safe authorization message without exposing exception details. The MCP server can also discover and deliver skills and their local resources, while preserving the existing tool catalog contract. Release validation now checks rendered metadata URLs for exact values rather than unsafe substrings.
