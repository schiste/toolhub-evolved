<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: ask-before-you-read -->
<!-- Release title: Ask Before You Read -->
<!-- Source range: 4eda3f4..bebc3d0 (7 commits) -->

# What's New for Users

- The English Wikipedia user-script directory now fills in over about 8 hours instead of 26. Until it is complete, coverage keeps saying so rather than letting a partial count read as the whole wiki.
- The census now asks each wiki whether it is keeping up before reading from it, and stops for the hour when the answer is no. A wiki under load is never made to serve a bulk reader.
- A run that stops early no longer skips the pages it did not reach. It resumes from exactly where it left off next hour, so nothing falls out of the directory because of one busy afternoon.
