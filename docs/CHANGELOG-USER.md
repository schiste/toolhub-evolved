<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: what-makes-a-gadget-a-gadget -->
<!-- Release title: What Makes A Gadget A Gadget -->
<!-- Source range: 001243d..05de929 (1 commit) -->

# What's New for Users

- On a wiki, a gadget is not simply a page of JavaScript. It is a gadget because it is registered on the wiki's gadget definition page, which is what puts it in everyone's Preferences and serves it to readers. Toolhub Evolved was deciding from the page's name instead, and the name is only the convention those pages follow.
- The difference matters most for gadgets that no longer exist. Retiring a gadget usually means deleting its line from that definition page and leaving the code behind, so the leftover page keeps a gadget's name forever. Pages written in advance of being registered look the same. Both were being catalogued as live gadgets.
- The catalogue now reads the definition page and believes what it says. A tool whose code is registered there is a gadget; one that is not is left without a type rather than given a wrong one, which is the safer answer for a field most tool records leave empty for us to fill.
- Nothing changes for gadgets that are genuinely registered, or for user scripts. A user script is settled by living on its author's own pages, and there is no register that could contradict that.
