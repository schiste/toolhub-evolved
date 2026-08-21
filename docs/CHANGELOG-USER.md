<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-bundle-is-not-a-gadget -->
<!-- Release title: A Bundle Is Not A Gadget -->
<!-- Source range: f237913..c7b49fb (3 commits) -->

# What's New for Users

- Gadget pages that are build output -- code assembled by a tool rather than typed by a maintainer -- are no longer read as the tool's own source. Reading one would have listed the libraries bundled into it as the tool's dependencies, and guesses like that quietly fill in blank fields on a tool's page as though someone had checked them.
- This finishes the change in the previous release. Lifting the size limit so that large gadgets could finally be read also let generated pages through, because those are large for an entirely different reason.
- Nothing already in the catalogue loses anything. Every wiki-hosted tool was re-checked against the new rule, and none of them has a page it removes.
