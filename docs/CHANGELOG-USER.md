<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: no-more-monday-bumps -->
<!-- Release title: No More Monday Bumps -->
<!-- Source range: 4205eec8..4392f5e7 (7 commits, promoted as four) -->

# What's New for Users

- Nothing changes on the site with this release. It records a maintenance decision about how the project's own dependencies are updated, so that the published history stays complete.
- Scheduled dependency-update pull requests are switched off. Four of them were open at once, each bundling many version bumps that nobody had asked for, and closing them by hand would only have brought the same bundles back the following Monday.
- Security updates are not affected. A fix for a known vulnerability in a dependency still arrives as a pull request and still has to pass the full test suite before it can be merged.
- Two security advisories published today against the project's own test tooling are fixed in the same release: the test runner moves to its first patched version, and a colour-parsing helper to its patched version. Neither touches anything the site serves; both had to be fixed for any change to pass the automated checks again.
