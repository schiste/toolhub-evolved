<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: say-what-was-actually-read -->
<!-- Release title: Say What Was Actually Read -->
<!-- Source range: 71dfd289..HEAD -->

# What's New for Users

- The mark on a gadget's keywords now says where they really came from. Hovering one used to read "read off the source code by a language model", which was not true of a gadget: its keywords are read from the description its own wiki shows, and the catalogue holds no copy of a gadget's source code to read. The mark now says so.
- A user script's keywords are unchanged and still say "source code", because that is what was read for them. The two kinds of reading now look different on the page because they are different, which is the entire reason the mark is there.
- Nothing else about the marks changed. A keyword a maintainer supplied still carries no mark, and the dagger still sits quietly beside the value rather than adding colour or a box to it.
