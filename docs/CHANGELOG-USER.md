<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: what-language-a-tool-speaks -->
<!-- Release title: What Language A Tool Speaks -->
<!-- Source range: be26eb07..HEAD -->

# What's New for Users

- The catalogue now records what language a user script speaks. Almost nothing did: 58 records of 57,811 said which languages their interface was available in, and not one gadget or user script among them. It is read from the words a script actually shows the person running it.
- Every language it carries, not just one. A script that keeps its own table of wording per language genuinely offers several, and about one in fifteen does; recording only the first would understate the work its author did.
- It is read carefully rather than guessed from where the script lives. A script on the Acehnese Wikipedia usually shows English text, so the wiki it sits on is a poor guide — only a third of answers matched the script's own wiki. Text a script merely rewrites, such as the alphabet tables in a transliteration tool, is ignored rather than counted as its interface.
- Where a script says it is translated, that link is recorded too — and only ever copied from the script itself, never composed. A link to a translation page that does not exist would be worse than no link at all, so one that is not written in the source is discarded.
- A reply the catalogue cannot read no longer counts as an answer. A question that came back as nonsense is asked again next time, instead of being quietly filed as settled.
