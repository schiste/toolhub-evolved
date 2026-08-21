<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: source-labels-complete -->
<!-- Release title: Every Source Says Its Name -->
<!-- Source range: e83a9a2..bf8b687 (1 commit) -->

# What's New for Users

- A user script's tool page no longer shows `wikimedia_user_script` where the name of a source should be. Tools hosted as a script in someone's user space on a wiki are recognised as such, and the evidence panel now calls that source a Wikimedia user script page.
- The same identifier was showing in the correction form, in the line that says which source a field's current value came from. It is now named there too, and translatable, so it does not stay English for readers of every other language.
- No source can reach a page unnamed again. Every kind of source the catalogue can cite is now checked against both places that display one, so a new kind cannot ship without a name the way this one and the gadget source both did.
