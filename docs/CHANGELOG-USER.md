<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: signing-in-is-connecting -->
<!-- Release title: Signing In Is Connecting -->
<!-- Source range: c7b49fb..03a6c32 (7 commits) -->

# What's New for Users

- Subscribing to a digest works again. Signing in with your Wikimedia account and then being told to connect a Wikimedia account was the whole bug, and it hit anyone who had signed in recently.
- There was never an action to take. Evolved has no separate "connect an account" step -- signing in is that step -- so the message was asking for something that does not exist. It has been replaced with one you can act on, for the rare case where the identity really is unavailable.
- Subscriptions you already have were unaffected, and nobody needs to sign in again to pick this up.
- Some tools link to a repository that is empty, or that holds only a note saying the code has moved somewhere else. Evolved now records that as the answer it is, rather than treating it as a scan that failed and trying again on a timer. Nothing changes on those tool pages -- there was never any code there to read -- but the scanner stops spending attempts on repositories that have nothing to give, and it will notice by itself if one of them is ever filled in.
- Digest editions now link tools to their Toolhub Evolved page. Every other link in a digest -- people, feeds, unsubscribe -- already pointed here, but the tool links sent you to official Toolhub instead, which meant each edition took readers away from the site that published it. The link text says "Toolhub Evolved page" to match. Editions already sent keep the links they went out with.
