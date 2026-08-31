<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: who-filled-this-field -->
<!-- Release title: Who Filled This Field -->
<!-- Source range: b569db8f..017b9f7e (1 commit) -->

# What's New for Users

- There is a new page, Data layer, linked from the footer. The statistics page already showed how complete the catalogue is, field by field. This one shows the same fields and adds the part that was missing: where each entry actually came from. Every field gets a bar split four ways, so you can see at a glance which parts of the catalogue people wrote, which parts the tools describe about themselves, which were read out of the source code, and which were written by a language model.
- The four kinds are kept apart on purpose, because they are not equally trustworthy and it would be easy to let them blur together. A description a maintainer wrote, a description a tool publishes about itself, a description worked out by reading the tool's code, and a description written by a model are four different claims, and the page never quietly presents one as another.
- The page also shows where a model's suggestion was set aside. A model is only ever allowed to fill a gap on this site; it can never replace something a person or a tool has already stated. Where it offered a value and something more reliable already existed, that is now counted and shown in its own column, so the page reports not only what was written for us but also how often we did not need it.
