<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: asking-only-what-is-missing -->
<!-- Release title: Asking Only What Is Missing -->
<!-- Source range: 70b04c35..HEAD -->

# What's New for Users

- The catalogue now asks about a tool only what it does not already know. It used to re-read a tool from scratch whenever it started collecting something new, working out a fresh description and fresh keywords in order to arrive at the one detail it was actually short of.
- That makes the current backlog much cheaper. About 45,000 gadgets and user scripts are being revisited purely to work out who they are for; each of those is now a single short question instead of three long ones.
- Adding a new kind of detail no longer needs a separate catch-up pass. Every tool that has never been asked about the new thing becomes due for it automatically, and every tool that has been asked is left alone — including one where the answer was "there is nothing to say", which is an answer and not a gap.
- Nothing changes about what is published or how it is marked. The same fields, the same checks on them, and the same small dagger saying which values the catalogue worked out rather than read from a maintainer.
