<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: say-what-was-actually-read -->
<!-- Release title: Say What Was Actually Read -->
<!-- Source range: 71dfd289..HEAD -->

# Technical and Marketing Notes

- Both inference lanes publish under `llm_inference`, deliberately: they are the same kind of claim, `SOURCE_CONFIDENCE` ranks them alike, and `FILL_ONLY_SOURCES` subordinates them alike. What they read is not the same, and the source string alone could not say — so roughly 10,000 gadget keywords were about to be labelled as read off source code that was never opened, because `wiki_gadgets` stores none.
- The lane travels beside the source in the evidence entry rather than becoming a second source string. A distinct source would have had to be added to `SOURCE_CONFIDENCE`, `FILL_ONLY_SOURCES` and the coverage buckets, and every one of those would have said the same thing as `llm_inference` — ranking is not what differs between the lanes, only the text that was read.
- `entry["lane"]` is absent unless a source declares one. Every provenance row written before this keeps exactly the shape it had, so no reader has to tell "no lane recorded" from "the old default", and a test asserts the user-script arm still writes none.
- The label lookup is scoped to `llm_inference` rather than reading any row that carries a lane. `lane` describes which text a model was given; a future transcribing source that recorded one would otherwise inherit a sentence about a language model that never ran. A test asserts a `wikimedia_user_script` row carrying `lane: "gadget"` keeps its own wording.
- Validation: 3,651 proxy tests with `catalog_projection` at 100% statement and branch coverage, 1,407 vitest tests including three new ones on the wording, `ruff check`/`format`, eslint, `tsc --checkJs`, prettier, cspell and the i18n extractor clean. Existing gadget rows re-mark on their next projection rebuild; nothing is re-sent to Lift Wing.
