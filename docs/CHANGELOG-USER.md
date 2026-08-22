<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: signing-in-is-connecting -->
<!-- Release title: Signing In Is Connecting -->
<!-- Source range: c7b49fb..6384171 (restored: this release describes the sign-in fix only) -->

# What's New for Users

- Subscribing to a digest works again. Signing in with your Wikimedia account and then being told to connect a Wikimedia account was the whole bug, and it hit anyone who had signed in recently.
- There was never an action to take. Evolved has no separate "connect an account" step -- signing in is that step -- so the message was asking for something that does not exist. It has been replaced with one you can act on, for the rare case where the identity really is unavailable.
- Subscriptions you already have were unaffected, and nobody needs to sign in again to pick this up.
