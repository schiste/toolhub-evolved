<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: reading-the-catalogue-faster -->
<!-- Release title: Reading The Catalogue Faster -->
<!-- Source range: 43d97a28..HEAD -->

# What's New for Users

- The catalogue reads new metadata about half again as fast. It works through tools a wave at a time, and the wave was six at once; it is now twelve, which was measured to be about 51% quicker.
- That matters right now because of a backlog. Every gadget and user script is being read again to work out who it is for, which is about 45,000 records — roughly twenty hours of reading at the old pace, and around thirteen at the new one.
- Twelve rather than more, on purpose. Eighteen at a time was measured too and was only 9% quicker again, because the service being asked starts queueing rather than going faster. It is a service shared with the rest of Wikimedia, so the extra load was not worth 9%.
