<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: asking-again-when-the-question-changed -->
<!-- Release title: Asking Again When The Question Changed -->
<!-- Source range: 77b26b1c..HEAD -->

# What's New for Users

- The audiences added in the last release will now actually reach the catalogue. They were only being read for tools the catalogue had not looked at before, which meant almost none of them: 46,491 records had already been read once and nothing would ever look at them again.
- The catalogue used to decide a tool had been read by asking whether its page had changed since. That is the right question when the reading is the same one, and the wrong question when a new thing is being read — the page had not changed, so nothing was re-read, so the new field stayed empty everywhere.
- It now also notices when it has started asking for something it did not ask for before, and reads those tools again. Tools nobody has ever read still go first, so this works through the backlog without delaying anything new.
- Expect audiences to appear gradually over the next day or two rather than all at once, for the same reason the keywords did: the reading is rate-limited and works through the catalogue a wave at a time.
