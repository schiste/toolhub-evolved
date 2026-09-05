<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: asking-only-what-is-missing -->
<!-- Release title: Asking Only What Is Missing -->
<!-- Source range: 70b04c35..HEAD -->

# Technical and Marketing Notes

- Each field is now a `Field` carrying everything needed to ask it: the words that request it, the rule its answer must survive, the room that answer needs in `max_tokens`, and the lanes that may produce it. A prompt is composed from the fields a row is missing rather than written out per lane — the alternative multiplies, since two lanes and three fields is already fourteen non-empty combinations to keep in step by hand.
- `asked_signature` records which questions a row has been put, sorted and comma-joined so the window can compare it as a scalar. It replaces `prompt_version`, which bought the same property once: a field added to `FIELD_ORDER` is missing from every row that predates it the same instant, with nothing to bump and no migration to remember.
- Keyed on what was asked, never on what came back. `accept` stores nothing for a field that produced nothing, so a payload cannot distinguish a field the model declined from one nobody asked about — a window reading the payload would re-ask the same unanswerable page every sweep for ever. A test asserts a fully-declined row leaves the window.
- `record` merges rather than replaces. A re-ask now covers only what was missing, so replacing the payload would drop the description and keywords a previous run paid for in order to store the one field this run went back for. A test asserts exactly that, because the failure would be silent and expensive.
- `max_tokens` is summed from the fields asked rather than fixed per lane. An audiences-only re-ask is 200 against 900 for a fresh user script, and generation is most of what a call costs — so the 45,047-row backfill gets materially cheaper on top of the concurrency change, rather than paying to regenerate three sentences it already has.
- `proxy/migrate.py` fills the new column from `prompt_version`, which is what keeps that saving. Left empty, every row would read as missing everything and the first sweep would re-ask 50,000 rows for a description and keywords they already hold. Verified against production-shaped rows: v1 rows come out complete, v0 rows come out missing only `audiences`, and a re-run updates nothing.
- Validation: 3,670 proxy tests with `inference_enrichment`, `models` and `db` all at 100% statement and branch coverage. Twenty-six existing tests moved to the new signatures rather than being loosened, and the English-keywords instruction moved from a lane's system prompt into the keywords fragment, so it now reaches every lane that asks for the field instead of the one that happened to mention it.
