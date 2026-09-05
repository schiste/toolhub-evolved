<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-licence-line-says-so-too -->
<!-- Release title: The Licence Line Says So Too -->
<!-- Source range: 4f9c0f0c..HEAD -->

# What's New for Users

- A gadget's licence now says where it came from. It is read off the wiki's own gadget definition rather than written by a maintainer, and it was the last line in the details block still shown without the small dagger that says so — the type, the wikis and the technologies beside it all carried one.
- The same slip had happened three times before this, always the same way. The keywords, then the wording on a gadget's keywords, then the audiences row: correct information, shown with nothing next to it saying it had been worked out rather than published. Each was noticed by somebody opening the page.
- It is now checked automatically instead. Every line in that block is declared as either something the catalogue worked out — which must carry the mark — or something a maintainer published, which must not. A new line added without that decision being made stops the build.
