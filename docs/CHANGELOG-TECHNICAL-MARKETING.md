<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: no-more-monday-bumps -->
<!-- Release title: No More Monday Bumps -->
<!-- Source range: 4205eec8..90c027fb (4 commits, promoted as two) -->

# Technical and Marketing Notes

- `.github/dependabot.yml` now sets `open-pull-requests-limit: 0` on all four update entries (npm development, GitHub Actions, and the two pip directories). That is GitHub's documented way to stop version updates for an ecosystem while leaving Dependabot security updates on; deleting the file would have dropped both.
- The trigger was operational: the four grouped PRs (155 to 158) were closed during a branch cleanup, and Dependabot's notice on each closed group PR states that closing ignores nothing and that only configuration does. An `@dependabot ignore this dependency` command was posted on each as well and drew no response, consistent with that notice.
- The graph index carries the config file, so the refresh is committed alongside, and the regenerated `CHANGELOG.md` covers the commits. No deploy is required for this release; the next Toolforge deploy records it in the manifest.
