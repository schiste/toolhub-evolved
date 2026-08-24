<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: who-the-gadget-is-for -->
<!-- Release title: Who the Gadget Is For -->
<!-- Source range: e61d34417..910a955 (6 commits) -->

# What's New for Users

- A gadget's report now says who the wiki actually serves it to. Every wiki keeps one page listing its gadgets, and a line there can restrict a gadget to administrators, to users who can revert edits, to anyone who can upload files. That restriction was sitting in plain text the whole time and the report ignored it. It is now listed among the tool's access rights, quoting the line and its number so you can open the page and check.
- The report also says when a gadget is on for everyone. Most gadgets are opt-in — you tick a box in your preferences. Some are switched on by default, which means every reader of that wiki runs them without ever choosing to. That is worth knowing about a piece of code, and it is now shown alongside the permission findings.
- Being restricted to a right is not treated as proof that the tool uses it. A wiki gates a rollback gadget on rollback because the gadget rolls back, but the line itself only says who is served. So a restriction on its own does not mark a tool as making changes, and does not move its health grade; only code the analysis actually read does that.
- Search no longer buries current tools under archived ones. Archived tools now sit behind a Status filter instead of being mixed into every result — on Meta alone the census counts 1,874 archived user scripts against 729 live ones, so the default was hiding what people were looking for. Tick Archived when you want them back.
- The feature status page had fallen behind what source analysis does. It listed the signals the analysis extracted when it first shipped and never mentioned browser permissions, endpoints, or the fact that gadgets and user scripts are read straight off the wiki they live on. It now describes both, and automatic repository analysis has an entry of its own.
