# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a description off a user script's source, for scripts that have none.

No model is reached. What is tested is the reasoning either side of the request:
which pages are worth paying to ask about, what is done with an answer that
cannot be trusted, and -- the part that decides whether this may run at all --
that nothing it produces can displace something a person or an upstream
registry said.

`REAL_REPLY` and `REAL_FENCED_REPLY` are what `llm-qwen36-27b` actually returned
through Lift Wing, kept verbatim rather than composed here: a validator tested
only on answers written to suit it cannot disagree with the validator.

They came from two different prompts, and both are worth keeping.
`REAL_REPLY` is this module's prompt, answered cleanly. `REAL_FENCED_REPLY` is
an earlier, wider prompt that also asked for a self-reported confidence -- it
arrived fenced despite the instruction not to fence, and carrying a key nobody
should now be asking for. That reply is the evidence for two decisions here:
that `parse_json` has to tolerate a fence, and that `accept` has to drop what it
was not asked for. Neither is hypothetical, and neither would be exercised by a
fixture written to match the current prompt.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import catalog_projection, db, userscripts  # noqa: E402
from backend import inference_enrichment as enrichment  # noqa: E402
from backend.models import ToolInference, UserScriptPage, utcnow  # noqa: E402

ENWIKI = "en.wikipedia.org"

# Lift Wing, llm-qwen36-27b, 2026-08-26, for the 15 KB source of
# User:Anomie/linkclassifier.js, through this module's own `payload_for`.
REAL_REPLY = """{
  "description": "This script analyzes links on a Wikipedia page and adds CSS classes to them \
based on the target page's categories, properties, and protection status. It visually \
distinguishes links pointing to disambiguation pages, deletion candidates, featured content, \
stubs, redirects, and other specific article types.",
  "keywords": ["links", "classification", "css", "categories", "disambiguation", "deletion",
               "redirects", "styling"]
}"""

# The same model and page through an earlier prompt that also asked for a
# confidence score. Fenced despite being told not to fence, and carrying a key
# the current prompt does not request.
REAL_FENCED_REPLY = """```json
{"description": "Adds colour coding to wiki links so you can tell at a glance whether a \
link points to a disambiguation page, a redirect, or a page that does not exist yet.", \
"keywords": ["links", "disambiguation", "redirects", "navigation"], \
"confidence": {"description": 0.9, "keywords": 0.85}}
```"""

REAL_REFUSAL = '{"description": null, "keywords": []}'


def reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


# --- helpers ---------------------------------------------------------------

BODY = "// a script long enough to be worth sending\n" + ("var x = 1;\n" * 20)


def store(title, *, owner="Anomie", basename="linkclassifier.js", body=BODY, fingerprint="f1", **kwargs):
    fields = {"role": userscripts.ROLE_SCRIPT, "deleted_at": None, "wiki": ENWIKI}
    fields.update(kwargs)
    with db.session_scope() as session:
        session.add(
            UserScriptPage(title=title, owner=owner, basename=basename, body=body, fingerprint=fingerprint, **fields)
        )


def names(candidates):
    return [candidate.title for candidate in candidates]


def rows():
    with db.session_scope() as session:
        return {row.tool_name: (row.status, row.payload, row.source_fingerprint) for row in session.query(ToolInference)}


def run(answer, *, limit=enrichment.BATCH):
    """Drive one pass with `answer` deciding each reply, and return the counts."""
    with db.session_scope() as session:
        return enrichment.infer(session, answer, model="llm-qwen36-27b", limit=limit)


# --- what an answer has to survive -----------------------------------------


def test_a_real_reply_survives_intact():
    accepted = enrichment.accept(enrichment.parse_json(enrichment.model_text(reply(REAL_REPLY))))
    assert set(accepted) == {"description", "keywords"}
    assert accepted["description"].startswith("This script analyzes links")
    assert accepted["keywords"][:2] == ["links", "classification"]


def test_a_fenced_reply_is_read_and_stripped_of_what_was_not_asked():
    accepted = enrichment.accept(enrichment.parse_json(enrichment.model_text(reply(REAL_FENCED_REPLY))))
    assert set(accepted) == {"description", "keywords"}
    assert "confidence" not in accepted
    assert accepted["description"].startswith("Adds colour coding")


def test_a_model_that_declines_contributes_nothing():
    assert enrichment.accept(enrichment.parse_json(REAL_REFUSAL)) == {}


def test_prose_saying_the_source_is_unclear_is_not_a_description():
    # Left unguarded this becomes the tool's description, and reads on the tool
    # page as though the tool were unclear rather than the reading of it.
    assert enrichment.accept({"description": "The source does not make the purpose clear at all."}) == {}


@pytest.mark.parametrize(
    "text",
    ["not json at all", "[1, 2, 3]", "```json\n{oops}\n```", ""],
    ids=["prose", "array", "broken-json-in-fence", "empty"],
)
def test_a_reply_that_cannot_be_read_is_rejected_rather_than_repaired(text):
    assert enrichment.parse_json(text) is None


def test_a_description_outside_the_length_bounds_is_dropped():
    assert enrichment.accept({"description": "Too short."}) == {}
    assert enrichment.accept({"description": "x " * 500}) == {}


def test_keywords_are_casefolded_deduped_and_capped():
    accepted = enrichment.accept({"keywords": ["Links", "links", *[f"tag{n}" for n in range(20)]]})
    assert accepted["keywords"][0] == "links"
    assert len(accepted["keywords"]) == enrichment.MAX_KEYWORDS
    assert len(set(accepted["keywords"])) == enrichment.MAX_KEYWORDS


@pytest.mark.parametrize(
    "keyword",
    ["https://example.invalid/x", "!!!", "a", "-leading-dash", "x" * 60],
    ids=["url", "punctuation", "too-short", "bad-start", "too-long"],
)
def test_a_keyword_that_would_pollute_the_facet_list_is_dropped(keyword):
    # A keyword becomes a facet value, and a facet value is permanent in a way a
    # description is not: it appears in the sidebar for everyone, forever.
    assert enrichment.accept({"keywords": [keyword]}) == {}


# --- what is worth asking about --------------------------------------------


def test_a_page_whose_source_has_already_been_read_is_not_sent_again():
    store("User:Anomie/linkclassifier.js")
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 1
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 0


def test_a_page_whose_source_moved_is_read_again():
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    with db.session_scope() as session:
        session.query(UserScriptPage).one().fingerprint = "f2"
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 1
    assert rows()["userscript-en.wikipedia.org-anomie-linkclassifier.js"][2] == "f2"


def test_a_page_that_failed_is_not_retried_ahead_of_pages_nobody_has_tried():
    # Without a stored row for the failure, every sweep spends its whole budget
    # on the same unanswerable page and never reaches the rest of the corpus.
    store("User:Anomie/linkclassifier.js")
    assert run(lambda payload: (_ for _ in ()).throw(RuntimeError("503")))["error"] == 1
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"role": userscripts.ROLE_SHIM},
        {"deleted_at": utcnow()},
        {"body": "// tiny"},
        {"owner": "", "basename": ""},
    ],
    ids=["not-a-script", "deleted", "nothing-to-read", "no-catalogue-name"],
)
def test_pages_with_nothing_to_offer_are_never_sent(kwargs):
    store("User:Someone/thing.js", **kwargs)
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 0


def test_one_pages_outage_does_not_end_the_sweep():
    store("User:A/one.js", owner="A", basename="one.js", fingerprint="a")
    store("User:B/two.js", owner="B", basename="two.js", fingerprint="b")

    def flaky(payload):
        if "one.js" in payload["messages"][1]["content"]:
            raise RuntimeError("connection reset")
        return reply(REAL_REPLY)

    counts = run(flaky)
    assert counts == {"asked": 2, "ready": 1, "rejected": 0, "error": 1}


def test_the_source_is_truncated_rather_than_the_page_skipped():
    store("User:Big/huge.js", owner="Big", basename="huge.js", body="var x = 1;\n" * 40_000)
    sent = []
    run(lambda payload: sent.append(payload) or reply(REAL_REPLY))
    assert len(sent) == 1
    assert len(sent[0]["messages"][1]["content"]) < enrichment.MAX_SOURCE_CHARS + 1_000


# --- what reaches the catalogue --------------------------------------------


def sources_for(name):
    with db.session_scope() as session:
        return catalog_projection._sources_by_tool(session, [name], reports={})


TOOL = "userscript-en.wikipedia.org-anomie-linkclassifier.js"


def test_a_stored_reading_reaches_the_projection_as_a_fill_only_source():
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    source = sources_for(TOOL)[TOOL][0]
    assert source["source"] == catalog_projection.SOURCE_INFERENCE
    assert source["source"] in catalog_projection.FILL_ONLY_SOURCES
    assert source["url"].endswith("User:Anomie/linkclassifier.js")


def test_a_reading_of_source_that_has_since_changed_is_not_shown():
    # It cannot be re-checked against anything -- only re-taken -- so until it
    # is, there is nothing to stand behind.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    with db.session_scope() as session:
        session.query(UserScriptPage).one().fingerprint = "moved"
    assert sources_for(TOOL) == {}


def test_a_rejected_reading_is_remembered_but_never_published():
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    assert rows()[TOOL][0] == enrichment.STATUS_REJECTED
    assert sources_for(TOOL) == {}


def assembled(name):
    """Return (record, evidence) the way the projection builds them."""
    with db.session_scope() as session:
        sources = catalog_projection._sources_by_tool(session, [name], reports={})
        record, evidence, _validation, _times = catalog_projection._assemble(name, sources[name])
        return record, evidence


def credited(evidence, field):
    """Return the source whose value the projection published for one field."""
    return next(item["source"] for item in evidence[field] if item.get("effective"))


def canonical(**record):
    from backend.models import CanonicalToolCache  # noqa: PLC0415 - only these tests need it

    now = utcnow()
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name=TOOL,
                record={"name": TOOL, "title": "linkclassifier", **record},
                source="toolhub",
                source_url="https://toolhub.wikimedia.org/",
                fetched_at=now,
                expires_at=now,
                stale_until=now,
            )
        )


def test_the_model_fills_a_description_nobody_had():
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    record, evidence = assembled(TOOL)
    assert record["description"].startswith("This script analyzes links")
    assert credited(evidence, "description") == catalog_projection.SOURCE_INFERENCE


def test_an_upstream_description_wins_and_the_model_is_kept_only_as_evidence():
    # The whole point of the fill-only class: what Toolhub, a toolinfo.json or a
    # person said is what the catalogue publishes, whatever the model read.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    canonical(description="Classifies links.", keywords=["ai"])
    record, evidence = assembled(TOOL)
    assert record["description"] == "Classifies links."
    assert credited(evidence, "description") == catalog_projection.SOURCE_CANONICAL
    # A list field is where a fill-only source would otherwise leak in: keywords
    # union across sources, so "cannot overwrite" is not enough on its own.
    assert record["keywords"] == ["ai"]
    inferred = [item for item in evidence["description"] if item["source"] == catalog_projection.SOURCE_INFERENCE]
    assert inferred and not inferred[0]["effective"]


def test_the_model_still_fills_a_field_the_upstream_record_left_empty():
    # Toolhub records routinely carry a description and no keywords. The gap is
    # per field, not per tool.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    canonical(description="Classifies links.")
    record, evidence = assembled(TOOL)
    assert record["description"] == "Classifies links."
    assert record["keywords"][:3] == ["links", "classification", "css"]
    assert credited(evidence, "keywords") == catalog_projection.SOURCE_INFERENCE
