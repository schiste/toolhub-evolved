<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: an-empty-repository-is-an-answer -->
<!-- Release title: An Empty Repository Is An Answer -->
<!-- Source range: aa4097a..141da81 (5 commits) -->

# What's New for Users

- Some tools link to a repository that is empty, or that holds only a note saying the code has moved somewhere else. Evolved now records that as the answer it is, rather than treating it as a scan that failed and trying again on a timer. Nothing changes on those tool pages -- there was never any code there to read -- but the scanner stops spending attempts on repositories that have nothing to give, and it will notice by itself if one of them is ever filled in.
- Digest editions now link tools to their Toolhub Evolved page. Every other link in a digest -- people, feeds, unsubscribe -- already pointed here, but the tool links sent you to official Toolhub instead, which meant each edition took readers away from the site that published it. The link text says "Toolhub Evolved page" to match where it goes.
- Digests you have already received keep the links they went out with. Published editions are never rewritten, so this changes the editions from here on rather than the archive behind them.
