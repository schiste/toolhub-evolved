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
import threading
from unittest import mock
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import catalog_projection, db, run_budget, tool_shape, userscripts  # noqa: E402
from backend import inference_enrichment as enrichment  # noqa: E402
from backend.models import (  # noqa: E402
    LANE_GADGET,
    ToolInference,
    UserScriptDirectoryEntry,
    UserScriptPage,
    WikiGadget,
    utcnow,
)
from backend.inference_enrichment import Candidate  # noqa: E402

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

# Lift Wing, llm-qwen36-27b, 2026-09-05, for `User:D2F0F5/linkclassifier.css` on
# meta, through this module's prompt once `audiences` was part of it. The one
# fixture here that a current prompt would produce whole, which is what
# `test_an_answer_that_was_accepted_whole_is_not_stored_twice` needs: every
# other real reply predates the third field and is legitimately missing it.
REAL_WHOLE_REPLY = """{
"description": "This stylesheet visually distinguishes different types of links on wiki pages by \
applying specific colors and outlines. It highlights stubs, new pages, redirects, disambiguation \
pages, and pages nominated for deletion to help users quickly identify link status.",
"keywords": ["css", "styling", "links", "redirects", "stubs", "deletion", "disambiguation", "visual"],
"audiences": ["editor", "reader"]
}"""




def reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    with application.app_context():
        yield


# --- helpers ---------------------------------------------------------------

BODY = "// a script long enough to be worth sending\n" + ("var x = 1;\n" * 20)

SCRIPT_FIELDS = ("description", "keywords", "audiences")
GADGET_FIELDS = ("keywords", "audiences")



def store(title, *, owner="Anomie", basename="linkclassifier.js", body=BODY, fingerprint="f1", original=True, **kwargs):
    """Seed one page, and by default the directory entry that makes it askable.

    `original=False` seeds the page alone, which is what a per-user copy looks
    like in the database: the census stored it, and the collapse folded it onto
    somebody else's script rather than giving it a directory row of its own.
    """
    fields = {"role": userscripts.ROLE_SCRIPT, "deleted_at": None, "wiki": ENWIKI}
    fields.update(kwargs)
    with db.session_scope() as session:
        session.add(
            UserScriptPage(title=title, owner=owner, basename=basename, body=body, fingerprint=fingerprint, **fields)
        )
        if original:
            session.add(
                UserScriptDirectoryEntry(
                    wiki=fields["wiki"], title=title, owner=owner, basename=basename, tier="active"
                )
            )


def names(candidates):
    return [candidate.title for candidate in candidates]


def rows():
    with db.session_scope() as session:
        return {row.tool_name: (row.status, row.payload, row.source_fingerprint) for row in session.query(ToolInference)}


def details():
    with db.session_scope() as session:
        return {row.tool_name: row.detail for row in session.query(ToolInference)}


def replies():
    with db.session_scope() as session:
        return {row.tool_name: row.reply for row in session.query(ToolInference)}


def forget_replies():
    """Blank the reply column, standing in for a row stored before it existed.

    NULL is the only mark those 4,260 rows carry, so a test that wants one has
    to produce it the way production did: store a rejection, then take the reply
    away. Constructing the row by hand instead would test the fixture.
    """
    with db.session_scope() as session:
        for row in session.query(ToolInference):
            row.reply = None


def outage(message="503 Server Error: Service Unavailable"):
    """An `ask` that fails the way Lift Wing did on 2026-08-26."""

    def answer(payload):
        raise RuntimeError(message)

    return answer


def age_inference(*, by):
    """Backdate every stored outcome, standing in for time passing between runs."""
    with db.session_scope() as session:
        for row in session.query(ToolInference):
            row.checked_at = utcnow() - by


def run(answer, *, limit=enrichment.BATCH):
    """Drive one pass with `answer` deciding each reply, and return the counts."""
    with db.session_scope() as session:
        return enrichment.infer(session, answer, model="llm-qwen36-27b", limit=limit)


# --- what an answer has to survive -----------------------------------------


def test_a_real_reply_survives_intact():
    accepted = enrichment.accept(enrichment.parse_json(enrichment.model_text(reply(REAL_REPLY))), SCRIPT_FIELDS)
    assert set(accepted) == {"description", "keywords"}
    assert accepted["description"].startswith("This script analyzes links")
    assert accepted["keywords"][:2] == ["links", "classification"]


def test_a_fenced_reply_is_read_and_stripped_of_what_was_not_asked():
    accepted = enrichment.accept(enrichment.parse_json(enrichment.model_text(reply(REAL_FENCED_REPLY))), SCRIPT_FIELDS)
    assert set(accepted) == {"description", "keywords"}
    assert "confidence" not in accepted
    assert accepted["description"].startswith("Adds colour coding")


def test_a_model_that_declines_contributes_nothing():
    assert enrichment.accept(enrichment.parse_json(REAL_REFUSAL), SCRIPT_FIELDS) == {}


def test_prose_saying_the_source_is_unclear_is_not_a_description():
    # Left unguarded this becomes the tool's description, and reads on the tool
    # page as though the tool were unclear rather than the reading of it.
    assert enrichment.accept({"description": "The source does not make the purpose clear at all."}, SCRIPT_FIELDS) == {}


@pytest.mark.parametrize(
    "text",
    ["not json at all", "[1, 2, 3]", "```json\n{oops}\n```", ""],
    ids=["prose", "array", "broken-json-in-fence", "empty"],
)
def test_a_reply_that_cannot_be_read_is_rejected_rather_than_repaired(text):
    assert enrichment.parse_json(text) is None


def test_a_description_outside_the_length_bounds_is_dropped():
    assert enrichment.accept({"description": "Too short."}, SCRIPT_FIELDS) == {}
    assert enrichment.accept({"description": "x " * 500}, SCRIPT_FIELDS) == {}


def test_keywords_are_casefolded_deduped_and_capped():
    accepted = enrichment.accept({"keywords": ["Links", "links", *[f"tag{n}" for n in range(20)]]}, SCRIPT_FIELDS)
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
    assert enrichment.accept({"keywords": [keyword]}, SCRIPT_FIELDS) == {}


def test_a_refusal_records_which_field_refused_and_why():
    # 4,253 rejections were stored with an empty `detail`, so the only way to
    # learn why the lane produced nothing was to re-ask the model.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    assert details()[TOOL] == (
        "description: absent or null in the reply; keywords: empty list; "
        "audiences: absent or null in the reply"
    )


def test_a_description_that_fails_while_keywords_pass_is_ready_and_still_says_what_is_missing():
    # `accept` returns the fields that survived, so one surviving keyword makes
    # the row `ready` with no description at all. Without the reason recorded
    # here, that row is indistinguishable from a described tool in every count.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply('{"description": "Too short.", "keywords": ["links"]}'))
    assert rows()[TOOL][0] == enrichment.STATUS_READY
    assert "description" not in rows()[TOOL][1]
    assert details()[TOOL] == (
        "description: 10 chars, wanted 20-600; audiences: absent or null in the reply"
    )


def test_a_reply_that_never_parsed_keeps_a_sample_of_what_came_back():
    # No field has a verdict when nothing parsed, so the reply is the only
    # evidence for whether the model went off-format or something upstream
    # answered in its place.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply("<html><body>502 Bad Gateway</body></html>"))
    assert details()[TOOL] == "unparsed reply: <html><body>502 Bad Gateway</body></html>"


def test_an_endpoint_failure_still_records_the_exception():
    store("User:Anomie/linkclassifier.js")
    run(outage())
    assert details()[TOOL] == "RuntimeError: 503 Server Error: Service Unavailable"


def test_a_refusal_keeps_the_words_that_were_refused():
    # `detail` names the rule that was broken; on its own it cannot say whether
    # the model wrote a bad answer or the prompt asked for the wrong thing. The
    # reply is the only thing that can, and re-asking to see it costs the call
    # again -- which for the 4,260 rows stored without it is the whole problem.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    assert replies()[TOOL] == REAL_REFUSAL


def test_an_answer_that_was_accepted_whole_is_not_stored_twice():
    # Nothing was refused, so there is nothing the reply explains that `payload`
    # does not already hold -- and this table is 37,791 rows wide. Uses the one
    # fixture answering all three fields: a reply missing `audiences` is not
    # accepted whole, and storing its words is then the right thing to do.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_WHOLE_REPLY))
    assert rows()[TOOL][0] == enrichment.STATUS_READY
    assert replies()[TOOL] == ""


def test_a_reply_too_long_to_keep_whole_is_cut_rather_than_dropped():
    # A malformed reply can be arbitrarily long -- an HTML error page, a model
    # that never stopped generating -- and the first characters are what say
    # which of those it was.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply("garbage " * 5_000))
    assert len(replies()[TOOL]) == enrichment.MAX_REPLY_CHARS


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


def test_a_page_that_failed_is_not_retried_on_the_very_next_sweep():
    # Without a stored row for the failure, every sweep spends its whole budget
    # on the same unanswerable page and never reaches the rest of the corpus.
    store("User:Anomie/linkclassifier.js")
    assert run(outage())["error"] == 1
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 0


def test_a_page_that_failed_is_asked_again_once_the_cooldown_has_passed():
    # The failure was a statement about Lift Wing, not about the script. Keyed
    # on the fingerprint and never revisited, it made one bad minute at the
    # endpoint into a tool that could never acquire a description.
    store("User:Anomie/linkclassifier.js")
    run(outage())
    age_inference(by=enrichment.RETRY_ERROR_AFTER + timedelta(minutes=1))
    assert run(lambda payload: reply(REAL_REPLY))["ready"] == 1
    assert rows()[TOOL][0] == enrichment.STATUS_READY


def test_a_rejected_answer_is_not_retried_however_long_it_sits():
    # A rejection is a statement about the answer, and the bytes it was read
    # from have not moved. Re-asking the same model about them buys the same
    # reply at full price, which is why only errors get a second chance.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    age_inference(by=enrichment.RETRY_ERROR_AFTER * 100)
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 0


def test_a_page_nobody_has_tried_is_offered_before_a_page_awaiting_a_retry():
    # The retry must only ever take a slot no untried page wanted, or a corpus
    # with a bad day behind it starves its own frontier.
    store("User:A/one.js", owner="A", basename="one.js", fingerprint="a")
    run(outage())
    age_inference(by=enrichment.RETRY_ERROR_AFTER + timedelta(minutes=1))
    store("User:B/two.js", owner="B", basename="two.js", fingerprint="b")
    with db.session_scope() as session:
        assert names(enrichment.pending(session)) == ["User:B/two.js", "User:A/one.js"]


def test_a_rejection_stored_before_the_reply_was_kept_is_asked_once_more():
    # The one exception to "rejections are never retried", and it is bounded by
    # what it is for: those rows recorded a verdict against words nobody kept,
    # so they can never be read. A re-ask is the only way they acquire them.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    forget_replies()
    age_inference(by=enrichment.RETRY_ERROR_AFTER * 100)
    assert run(lambda payload: reply(REAL_REPLY))["ready"] == 1


def test_a_backfilled_rejection_is_never_offered_again():
    # "Once" is the predicate, not a counter: the re-ask writes the column, and
    # writing it is what removes the row from the arm that selected it.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    forget_replies()
    assert run(lambda payload: reply(REAL_REFUSAL))["asked"] == 1
    assert run(lambda payload: reply(REAL_REFUSAL))["asked"] == 0


def test_a_backfill_the_endpoint_refused_leaves_the_backfill_and_joins_the_retries():
    # An outage during the backfill must not consume the row's one turn. It
    # leaves this arm all the same -- the column is written -- but as an
    # `error`, which the cooldown offers again on its own terms.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    forget_replies()
    assert run(outage())["error"] == 1
    assert run(lambda payload: reply(REAL_REPLY))["asked"] == 0
    age_inference(by=enrichment.RETRY_ERROR_AFTER + timedelta(minutes=1))
    assert run(lambda payload: reply(REAL_REPLY))["ready"] == 1


def test_the_backfill_takes_only_slots_the_other_two_did_not_want():
    # Three tiers, and the newest is the cheapest to postpone: a page nobody has
    # described is worth more than a second reading of one already answered.
    store("User:A/one.js", owner="A", basename="one.js", fingerprint="a")
    run(lambda payload: reply(REAL_REFUSAL))
    store("User:B/two.js", owner="B", basename="two.js", fingerprint="b")
    # A is a rejection carrying its reply at this point, so this sweep passes
    # over it and only B fails. Taking A's reply away afterwards is what makes
    # it a legacy row -- doing it before would put A in this outage too.
    run(outage())
    age_inference(by=enrichment.RETRY_ERROR_AFTER + timedelta(minutes=1))
    forget_replies()
    store("User:C/three.js", owner="C", basename="three.js", fingerprint="c")
    with db.session_scope() as session:
        assert names(enrichment.pending(session)) == ["User:C/three.js", "User:B/two.js", "User:A/one.js"]


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
    # Keywords are the one field where the fill-only rule yields, and only below
    # KEYWORD_FILL_FLOOR: one keyword usually means the record mentioned one
    # rather than that somebody chose one. What must not yield is provenance --
    # the merged value keeps its own evidence row saying a model supplied it, and
    # the tag carries a mark, so nothing here is published as the maintainer's.
    assert record["keywords"][0] == "ai"
    assert len(record["keywords"]) <= catalog_projection.KEYWORD_FILL_CEILING
    keyword_sources = {item["value"]: item["source"] for item in evidence["keywords"] if item["effective"]}
    assert keyword_sources["ai"] == catalog_projection.SOURCE_CANONICAL
    assert set(keyword_sources.values()) >= {catalog_projection.SOURCE_INFERENCE}
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


# --- the answer has to reach the page somebody reads ------------------------


def sweep_with(answer, monkeypatch):
    """Drive `sweep`, capturing the tool names it asks the projection to rebuild."""
    rebuilt = []
    monkeypatch.setattr(enrichment, "liftwing_caller", lambda: answer)
    monkeypatch.setattr(enrichment, "configured_model", lambda: "llm-qwen36-27b")
    monkeypatch.setattr(catalog_projection, "refresh_tool_names", lambda names: rebuilt.extend(names) or {})
    return enrichment.sweep(limit=enrichment.BATCH), rebuilt


def test_a_sweep_rebuilds_the_projection_for_what_it_filled(monkeypatch):
    # catalog_projection's own sweep is a 500-an-hour backstop, so without this
    # the answer sits in the table for days before anybody could read it.
    store("User:Anomie/linkclassifier.js")
    _result, rebuilt = sweep_with(lambda payload: reply(REAL_REPLY), monkeypatch)
    assert rebuilt == [TOOL]


def test_a_sweep_that_filled_nothing_rebuilds_nothing(monkeypatch):
    store("User:Anomie/linkclassifier.js")
    result, rebuilt = sweep_with(lambda payload: reply(REAL_REFUSAL), monkeypatch)
    assert rebuilt == []
    assert result["projection"] == {"requested": 0, "refreshed": 0, "changed": 0, "errors": 0}


def test_a_per_user_copy_is_never_paid_for():
    """A page the collapse folded onto somebody else's script is not asked about.

    This is the whole reason the directory join exists. `LiveRCparam.js` is the
    real shape: hundreds of people keep their own settings under one filename,
    every one of them is a `ROLE_SCRIPT` page the census stored, and exactly one
    of them is a script anybody could publish a description for.
    """
    store("User:Anomie/linkclassifier.js")
    store("User:Someone/LiveRCparam.js", owner="Someone", basename="LiveRCparam.js", original=False)
    store("User:Another/LiveRCparam.js", owner="Another", basename="LiveRCparam.js", original=False)

    with db.session_scope() as session:
        assert names(enrichment.pending(session)) == ["User:Anomie/linkclassifier.js"]


def test_a_user_stylesheet_is_never_paid_for():
    """A CSS page is in the directory and is not a tool.

    `userscript_toolinfo` drops it from the catalogue, so a description written
    for it has nowhere to go. It is excluded here rather than after the model
    has been paid, which is where the old filter left it.
    """
    store("User:Anomie/vector.css", basename="vector.css", content_model="sanitized-css")

    with db.session_scope() as session:
        assert names(enrichment.pending(session)) == []


def test_the_reported_denominator_is_the_one_the_sweep_actually_works_through():
    """`coverage` counts what `pending` would consider, not every stored page.

    The two drifting apart is not cosmetic: a denominator that counts copies and
    stylesheets reported 166,399 pages for 48,700 of work, which is the
    difference between a lane three weeks from done and one seven weeks away.
    """
    store("User:Anomie/linkclassifier.js")
    store("User:Someone/LiveRCparam.js", owner="Someone", basename="LiveRCparam.js", original=False)
    store("User:Anomie/vector.css", basename="vector.css", content_model="sanitized-css")
    store("User:Anomie/stub.js", basename="stub.js", fingerprint="f2", body="// hi")

    with db.session_scope() as session:
        considered = len(enrichment.pending(session))
    assert enrichment.coverage()["eligiblePages"] == considered == 1


def test_the_window_does_not_carry_the_source_it_is_not_asking_about():
    """`pending` holds no bodies, however large the backlog it windows.

    This is the bug, and it is invisible in the output: the sweep asked about
    the right pages and stored the right answers while `pending` also loaded
    every windowed page's source to do it. At 19,390 windowed pages that was
    260 MB of script text and 546 MB resident against a 512Mi job, so the run
    was OOM-killed -- silently, because SIGKILL leaves no summary, no
    `job_runs` row, and a job-guard lock nobody releases. Asserting on names
    would pass either way, so this asserts on what the run holds.
    """
    store("User:Anomie/linkclassifier.js", body="x" * 200_000)
    store("User:Anomie/two.js", basename="two.js", fingerprint="f2", body="y" * 200_000)

    with db.session_scope() as session:
        candidates = enrichment.pending(session)
    assert len(candidates) == 2
    assert sum(len(candidate.body) for candidate in candidates) == 0


def test_a_page_too_short_to_describe_never_reaches_the_window():
    """The floor moved into SQL, so short pages stop occupying window slots.

    They leave no row when skipped, so under the old Python filter every sweep
    re-read and re-skipped the same pages forever, each one costing a slot in
    a window that is the only thing bounding the run.
    """
    store("User:Anomie/linkclassifier.js")
    store("User:Anomie/stub.js", basename="stub.js", fingerprint="f2", body="// hi")

    with db.session_scope() as session:
        assert names(enrichment.pending(session)) == ["User:Anomie/linkclassifier.js"]


def test_source_is_read_for_the_pages_about_to_be_asked_about():
    store("User:Anomie/linkclassifier.js")

    with db.session_scope() as session:
        wave = enrichment.with_source(session, enrichment.pending(session))
    assert [candidate.body for candidate in wave] == [BODY]
    assert [candidate.fingerprint for candidate in wave] == ["f1"]


def test_a_page_that_moves_between_the_window_and_the_wave_is_dropped():
    """The census rewrites pages while a sweep runs, and a run is many minutes.

    Dropped rather than asked about: the page leaves no row, so the next sweep
    reconsiders it against whatever it says then.
    """
    store("User:Anomie/linkclassifier.js")
    with db.session_scope() as session:
        candidates = enrichment.pending(session)

    with db.session_scope() as session:
        session.query(UserScriptPage).update({"body": "// gone"})

    with db.session_scope() as session:
        assert enrichment.with_source(session, candidates) == []


def test_the_wave_carries_the_fingerprint_of_the_source_it_read():
    """Body and fingerprint are read together, so the pair cannot disagree.

    Recording an answer against a fingerprint the source has moved past would
    claim the page was checked at a revision nobody asked about, and the next
    sweep would trust that row and skip it.
    """
    store("User:Anomie/linkclassifier.js")
    with db.session_scope() as session:
        candidates = enrichment.pending(session)

    with db.session_scope() as session:
        session.query(UserScriptPage).update({"body": "z" * 500, "fingerprint": "f2"})

    with db.session_scope() as session:
        wave = enrichment.with_source(session, candidates)
    assert [(candidate.body, candidate.fingerprint) for candidate in wave] == [("z" * 500, "f2")]


# --- how fast a run is allowed to go ----------------------------------------


def test_a_wave_asks_about_several_pages_at_once(monkeypatch):
    """Concurrency is what makes the backlog finishable, so assert it, not the count.

    Six pages and a width of three: the endpoint must see three calls
    overlapping. A barrier that all three have to reach before any returns is
    the only way this passes serially -- it would deadlock instead.
    """
    for index in range(6):
        store(f"User:Anomie/s{index}.js", basename=f"s{index}.js", fingerprint=f"f{index}")
    monkeypatch.setenv("LIFTWING_CONCURRENCY", "3")
    barrier = threading.Barrier(3, timeout=10)

    def answer(_payload):
        barrier.wait()
        return reply(REAL_REPLY)

    result, _rebuilt = sweep_with(answer, monkeypatch)

    assert result["concurrency"] == 3
    assert result["counts"]["asked"] == 6
    assert result["counts"]["ready"] == 6


def test_a_run_stops_between_waves_when_its_budget_is_spent(monkeypatch):
    """The deadline bounds a scheduled run, and it never abandons a wave mid-flight.

    Four pages, width two, and a clock that expires during the first wave. Both
    of its pages are still stored -- a half-written wave would throw away
    answers already paid for -- and the second wave is never started.
    """
    for index in range(4):
        store(f"User:Anomie/s{index}.js", basename=f"s{index}.js", fingerprint=f"f{index}")
    monkeypatch.setenv("LIFTWING_CONCURRENCY", "2")
    ticks = iter([0.0, 0.0, 30.0, 30.0, 30.0])
    monkeypatch.setattr(enrichment, "liftwing_caller", lambda: (lambda _payload: reply(REAL_REPLY)))
    monkeypatch.setattr(enrichment, "configured_model", lambda: "llm-qwen36-27b")
    monkeypatch.setattr(catalog_projection, "refresh_tool_names", lambda names: {})  # noqa: ARG005

    result = enrichment.sweep(limit=enrichment.BATCH, budget=run_budget.Budget(1, clock=lambda: next(ticks)))

    assert result["counts"]["asked"] == 2
    assert len(rows()) == 2


def test_a_nonsense_concurrency_setting_never_opens_more_sockets_than_the_cap(monkeypatch):
    monkeypatch.setenv("LIFTWING_CONCURRENCY", "500")
    assert enrichment.concurrency() == enrichment.MAX_CONCURRENCY
    monkeypatch.setenv("LIFTWING_CONCURRENCY", "not a number")
    assert enrichment.concurrency() == enrichment.DEFAULT_CONCURRENCY
    monkeypatch.setenv("LIFTWING_CONCURRENCY", "0")
    assert enrichment.concurrency() == 1


# --- replies that are not the shape the contract assumes -------------------


@pytest.mark.parametrize(
    "response",
    ["not a mapping", {}, {"choices": "not a list"}, {"choices": []}, {"choices": [{}]}],
    ids=["not-a-dict", "no-choices", "choices-not-a-list", "no-choices-at-all", "choice-without-message"],
)
def test_a_response_that_is_not_a_chat_completion_yields_no_text(response):
    # The endpoint is reached over the network and its body is untrusted JSON:
    # an error envelope must read as "no answer", never raise inside a sweep
    # that still has hundreds of pages to get through.
    assert enrichment.model_text(response) == ""


def test_an_unterminated_fence_leaves_nothing_to_parse():
    assert enrichment.parse_json("```") is None


@pytest.mark.parametrize(
    "value",
    [42, {"text": "a description"}, ["a description"]],
    ids=["number", "object", "array"],
)
def test_a_description_that_is_not_prose_is_refused_by_type(value):
    assert enrichment.check({"description": value}, SCRIPT_FIELDS).get("description").reason.startswith("not a string")


def test_a_description_carrying_a_link_is_refused():
    # A description is rendered on the tool page. A URL the model invented
    # there is a link this site would be publishing on somebody else's behalf.
    verdict = enrichment.check({"description": "A gadget documented at https://example.invalid/docs page."}, SCRIPT_FIELDS)
    assert verdict["description"] == enrichment.Checked("", "contains a URL")


def test_keywords_offered_as_anything_but_a_list_are_refused_by_type():
    assert enrichment.check({"keywords": "links, css"}, SCRIPT_FIELDS)["keywords"].reason == "not a list (str)"


def test_a_keyword_list_mixing_prose_and_junk_keeps_only_the_strings():
    accepted = enrichment.accept({"keywords": ["links", 7, None, {"tag": "css"}, "css"]}, SCRIPT_FIELDS)

    assert accepted["keywords"] == ["links", "css"]


def test_a_reply_that_parsed_to_nothing_stores_nothing():
    # `accept` is the last gate before a value is written under a person's
    # name, so it has to hold for the empty reply as well as the bad one.
    assert enrichment.accept(None, SCRIPT_FIELDS) == {}
    assert enrichment.accept({}, SCRIPT_FIELDS) == {}


def test_reading_source_for_an_empty_wave_asks_the_database_nothing():
    with db.session_scope() as session:
        assert enrichment.with_source(session, []) == []


# --- binding the caller to the configured endpoint -------------------------


LIFTWING_ENDPOINT = (
    "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions"
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.raised = False

    def raise_for_status(self):
        self.raised = True

    def json(self):
        return self.payload


class _FakeSession:
    """One `requests.Session`, recording how many of it a run opens."""

    opened: list["_FakeSession"] = []

    def __init__(self):
        type(self).opened.append(self)
        self.posts = []

    def post(self, url, *, json, headers, timeout):
        self.posts.append((url, json, headers, timeout))
        return _FakeResponse(reply(REAL_REPLY))


@pytest.fixture
def _liftwing(monkeypatch):
    monkeypatch.setenv("LIFTWING_API_URL", LIFTWING_ENDPOINT)
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")
    monkeypatch.delenv("LIFTWING_USER_AGENT", raising=False)
    monkeypatch.delenv("LIFTWING_TIMEOUT_SECONDS", raising=False)
    _FakeSession.opened = []
    monkeypatch.setattr(enrichment.requests, "Session", _FakeSession)


def test_the_caller_posts_to_the_allowlisted_endpoint_and_identifies_this_tool(_liftwing):
    ask = enrichment.liftwing_caller()

    assert enrichment.model_text(ask({"messages": []})) == REAL_REPLY

    url, _payload, headers, timeout = _sole_post()
    assert url == LIFTWING_ENDPOINT
    # Wikimedia asks every client to say who it is, on both header spellings.
    assert headers["User-Agent"] == enrichment.DEFAULT_USER_AGENT
    assert headers["Api-User-Agent"] == enrichment.DEFAULT_USER_AGENT
    assert timeout == enrichment.DEFAULT_TIMEOUT_SECONDS


def _sole_post():
    """The single request the one opened session recorded."""
    [session] = _FakeSession.opened
    return session.posts[0]


def test_one_thread_reuses_its_connection_across_pages(_liftwing):
    ask = enrichment.liftwing_caller()

    ask({"messages": []})
    ask({"messages": []})

    # A bare `requests.post` would pay a TLS handshake per page, which at this
    # concurrency is most of what the endpoint sees.
    assert len(_FakeSession.opened) == 1


def test_each_worker_thread_gets_a_connection_of_its_own(_liftwing):
    ask = enrichment.liftwing_caller()
    started = threading.Barrier(2, timeout=10)

    def call():
        started.wait()
        ask({"messages": []})

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # One shared Session across threads is not documented as safe; thread-local
    # storage is what buys pooling without that question.
    assert len(_FakeSession.opened) == 2


def test_a_timeout_below_a_second_is_raised_to_one(_liftwing, monkeypatch):
    monkeypatch.setenv("LIFTWING_TIMEOUT_SECONDS", "0")
    ask = enrichment.liftwing_caller()
    ask({"messages": []})

    assert _sole_post()[3] == 1


def test_the_configured_model_is_empty_when_inference_is_switched_off(monkeypatch):
    monkeypatch.delenv("LIFTWING_MODEL", raising=False)
    assert enrichment.configured_model() == ""
    monkeypatch.setenv("LIFTWING_MODEL", "  llm-qwen36-27b  ")
    assert enrichment.configured_model() == "llm-qwen36-27b"


def test_a_wave_whose_pages_all_vanished_costs_no_request(monkeypatch):
    """Every page in a slice can go away between the window and the wave.

    The census rewrites pages mid-run, so a slice can be emptied by deletions
    or by bodies shrinking below the floor. That is not the end of the sweep --
    the waves behind it are still worth asking about.
    """
    for index in range(4):
        store(f"User:Anomie/s{index}.js", basename=f"s{index}.js", fingerprint=f"f{index}")
    monkeypatch.setenv("LIFTWING_CONCURRENCY", "2")
    asked: list[object] = []
    monkeypatch.setattr(enrichment, "liftwing_caller", lambda: (lambda payload: asked.append(payload) or reply(REAL_REPLY)))
    monkeypatch.setattr(enrichment, "configured_model", lambda: "llm-qwen36-27b")
    monkeypatch.setattr(catalog_projection, "refresh_tool_names", lambda names: {})  # noqa: ARG005
    real_with_source = enrichment.with_source
    emptied = []

    def with_source(session, candidates):
        """Empty the first wave only, as deletions mid-run would."""
        if not emptied:
            emptied.append(candidates)
            return []
        return real_with_source(session, candidates)

    monkeypatch.setattr(enrichment, "with_source", with_source)

    result = enrichment.sweep(limit=enrichment.BATCH)

    # The first wave is skipped without a request; the second is still asked.
    assert result["counts"]["asked"] == 2
    assert len(asked) == 2


# --- the gadget lane -------------------------------------------------------
#
# Lift Wing, llm-qwen36-27b, 2026-09-04, through this module's own gadget
# prompt, for three gadgets whose descriptions their wikis write in Abkhaz
# Wikipedia's Russian, Acehnese and French. They are kept verbatim for the
# reason the user-script fixtures are: the one thing worth testing here is
# whether a prompt that demands English tags gets them from a description that
# is not in English, and a reply composed to prove that cannot.
REAL_GADGET_REPLY_RU = '{"keywords": ["block", "user", "text", "formatting", "list"]}'
REAL_GADGET_REPLY_ACE = '{"keywords": ["site notices", "announcements", "advanced"]}'
REAL_GADGET_REPLY_FR = """{
  "keywords": [
    "categories",
    "editing",
    "categorization",
    "maintenance",
    "wiki",
    "management",
    "bulk",
    "interface"
  ]
}"""

RU_DESCRIPTION = "Markblocked: зачёркивать имена пользователей, которые заблокированы."


def gadget(name="markblocked", *, wiki="ab.wikipedia.org", description=RU_DESCRIPTION, **kwargs):
    """Seed one live declared gadget carrying a description."""
    fields = {"wiki": wiki, "name": name, "name_key": name.casefold(), "description": description}
    fields.update(kwargs)
    with db.session_scope() as session:
        row = WikiGadget(**fields)
        session.add(row)
        session.flush()
        return row.id


def test_non_english_description_yields_english_keywords():
    """The whole reason the gadget prompt names English explicitly.

    71% of gadget descriptions are written in their wiki's own language, and
    `_KEYWORD_RE` admits ASCII only. A faithful Abkhaz tag would be dropped by
    shape validation and stored as a rejection, which would read as the model
    having failed when it had answered correctly.
    """
    accepted = enrichment.accept(enrichment.parse_json(REAL_GADGET_REPLY_RU), GADGET_FIELDS)
    assert accepted == {"keywords": ["block", "user", "text", "formatting", "list"]}
    for reply_text in (REAL_GADGET_REPLY_ACE, REAL_GADGET_REPLY_FR):
        tags = enrichment.accept(enrichment.parse_json(reply_text), GADGET_FIELDS)["keywords"]
        assert tags, "a real reply produced no keyword that survived shape validation"
        assert all(tag.isascii() for tag in tags)


def test_gadget_lane_cannot_store_a_description():
    """A gadget already has a maintainer's sentence; this lane may not add one.

    Structural, not a property of the prompt: a model that volunteers a
    description anyway has it dropped, the same way an unasked-for `license` is.
    """
    reply_with_prose = '{"description": "%s", "keywords": ["categories"]}' % ("x" * 80)
    assert enrichment.accept(enrichment.parse_json(reply_with_prose), GADGET_FIELDS) == {
        "keywords": ["categories"]
    }
    assert "description" in enrichment.accept(enrichment.parse_json(reply_with_prose), SCRIPT_FIELDS)


def test_description_fingerprint_ignores_reflowing():
    """A rewrapped message is not a rewritten one.

    10,049 gadgets re-asked over a stray newline would spend the lane's whole
    budget returning the answers it already had.
    """
    assert enrichment.description_fingerprint("a  b\n c") == enrichment.description_fingerprint("a b c")
    assert enrichment.description_fingerprint("a b") != enrichment.description_fingerprint("a c")


def test_gadget_pending_skips_gadgets_with_no_description():
    """21% of live gadgets have no description, so there is nothing to tag.

    Excluded from the window rather than sent and rejected, so that `rejected`
    keeps meaning "asked, and the answer was no good" in both lanes.
    """
    gadget("described")
    gadget("undescribed", description="")
    with db.session_scope() as session:
        found = enrichment.gadget_pending(session, limit=10)
    assert [candidate.title for candidate in found] == ["described"]
    assert found[0].lane == LANE_GADGET


def test_gadget_pending_skips_a_gadget_whose_answer_is_current():
    """Current means both halves: the source has not moved and the prompt has not grown.

    The fingerprint is what stops the lane paying for the same answer twice, and
    `prompt_version` is what stops it calling an answer complete when a field
    has since been added to the question.
    """
    gadget_id = gadget()
    with db.session_scope() as session:
        session.add(
            ToolInference(
                tool_name="gadget-ab-wikipedia-org-markblocked",
                payload={"keywords": ["block"]},
                lane=LANE_GADGET,
                page_id=gadget_id,
                source_fingerprint=enrichment.description_fingerprint(RU_DESCRIPTION),
                status=enrichment.STATUS_READY,
                asked_signature=enrichment.lane_signature(LANE_GADGET),
            )
        )
    with db.session_scope() as session:
        assert enrichment.gadget_pending(session, limit=10) == []


def test_gadget_pending_returns_a_gadget_whose_description_changed():
    """A wiki that rewrites the message puts its gadget back in the window."""
    gadget_id = gadget()
    with db.session_scope() as session:
        session.add(
            ToolInference(
                tool_name="gadget-ab-wikipedia-org-markblocked",
                payload={"keywords": ["block"]},
                lane=LANE_GADGET,
                page_id=gadget_id,
                source_fingerprint=enrichment.description_fingerprint("something the wiki used to say"),
                status=enrichment.STATUS_READY,
            )
        )
    with db.session_scope() as session:
        assert [c.title for c in enrichment.gadget_pending(session, limit=10)] == ["markblocked"]


def test_gadget_pending_skips_a_deleted_gadget():
    gadget("gone", deleted_at=utcnow())
    with db.session_scope() as session:
        assert enrichment.gadget_pending(session, limit=10) == []


def test_gadget_pending_skips_a_name_that_slugs_to_nothing():
    """`gadget_toolinfo.tool_name` refuses a name with no Latin characters."""
    gadget("гаджет")
    with db.session_scope() as session:
        assert enrichment.gadget_pending(session, limit=10) == []


def test_interleave_gives_each_lane_half_of_every_wave():
    """Concatenating would starve the newer lane behind ~8,000 unasked scripts."""
    scripts = [Candidate(f"s{i}", i, ENWIKI, "t", "b", "f") for i in range(2)]
    gadgets = [Candidate(f"g{i}", i, ENWIKI, "t", "b", "f", LANE_GADGET) for i in range(3)]
    assert [c.tool_name for c in enrichment._interleave(scripts, gadgets)] == ["s0", "g0", "s1", "g1", "g2"]


def test_with_source_passes_gadget_candidates_through():
    """A gadget carries its own text; re-reading it would only widen the race."""
    candidate = Candidate("gadget-x", 7, "ab.wikipedia.org", "markblocked", RU_DESCRIPTION, "fp", LANE_GADGET)
    with db.session_scope() as session:
        assert enrichment.with_source(session, [candidate]) == [candidate]


GADGET_TOOL = "gadget-ab-wikipedia-org-markblocked"


def store_gadget_inference(fingerprint_source=RU_DESCRIPTION, *, keywords=("block", "user")):
    gadget_id = gadget()
    with db.session_scope() as session:
        session.add(
            ToolInference(
                tool_name=GADGET_TOOL,
                payload={"keywords": list(keywords)},
                lane=LANE_GADGET,
                page_id=gadget_id,
                source_fingerprint=enrichment.description_fingerprint(fingerprint_source),
                status=enrichment.STATUS_READY,
            )
        )


def test_gadget_keywords_reach_the_projection_as_a_fill_only_source():
    """All 10,882 gadget records sit at zero keywords, which is the gap this fills."""
    store_gadget_inference()
    source = sources_for(GADGET_TOOL)[GADGET_TOOL][0]
    assert source["source"] == catalog_projection.SOURCE_INFERENCE
    assert source["source"] in catalog_projection.FILL_ONLY_SOURCES
    assert source["payload"] == {"keywords": ["block", "user"]}
    assert "Special:Gadgets" in source["url"]


def test_a_gadget_reading_of_a_description_the_wiki_has_rewritten_is_dropped():
    """Same rule the script arm applies to changed bytes, against changed words.

    The row stays -- the sweep still knows the gadget was asked about -- but
    nothing it says is published until it has been re-read.
    """
    store_gadget_inference("what the wiki said last month")
    assert sources_for(GADGET_TOOL) == {}


def test_a_deleted_gadget_publishes_no_keywords():
    """A gadget the wiki has stopped declaring is not a tool to tag."""
    store_gadget_inference()
    with db.session_scope() as session:
        session.query(WikiGadget).update({"deleted_at": utcnow()})
    assert sources_for(GADGET_TOOL) == {}


def test_the_two_lanes_do_not_read_each_others_rows():
    """`page_id` means different tables per lane, so a cross-read is silent nonsense.

    A user-script row whose `page_id` happens to equal a gadget's id must not
    surface as that gadget's keywords, which is the whole reason `lane` is read
    with `page_id` and never without it.
    """
    gadget_id = gadget()
    with db.session_scope() as session:
        session.add(
            ToolInference(
                tool_name=GADGET_TOOL,
                payload={"keywords": ["from-the-wrong-lane"]},
                lane=enrichment.LANE_USER_SCRIPT,
                page_id=gadget_id,
                source_fingerprint=enrichment.description_fingerprint(RU_DESCRIPTION),
                status=enrichment.STATUS_READY,
            )
        )
    assert sources_for(GADGET_TOOL) == {}


# --- what the tool page is told the record is -------------------------------


def test_a_declined_skin_file_is_projected_as_configuration():
    """The checklist has to stop being addressed to somebody who is not there.

    End to end rather than against `tool_shape` alone: the classification is
    only worth anything if it survives the join from catalogue name back to the
    page, which is the part that has no stored mapping to rely on.
    """
    store("User:DerHexer/monobook.js", owner="DerHexer", basename="monobook.js")
    run(lambda payload: reply(REAL_REFUSAL))
    catalog_projection.refresh_tool_names(["userscript-en.wikipedia.org-derhexer-monobook.js"])
    payload = catalog_projection.projection_payload("userscript-en.wikipedia.org-derhexer-monobook.js")
    assert payload["shape"] == tool_shape.SHAPE_SKIN


def test_a_script_the_model_described_keeps_its_checklist():
    """The other direction, and the one a wrong rule would break silently."""
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    catalog_projection.refresh_tool_names([TOOL])
    assert catalog_projection.projection_payload(TOOL)["shape"] == tool_shape.SHAPE_STANDALONE


def test_a_reclassified_page_counts_as_a_change():
    """A shape that flips has to republish, or the tool page keeps the old panel."""
    store("User:DerHexer/monobook.js", owner="DerHexer", basename="monobook.js")
    name = "userscript-en.wikipedia.org-derhexer-monobook.js"
    catalog_projection.refresh_tool_names([name])
    assert catalog_projection.projection_payload(name)["shape"] == tool_shape.SHAPE_STANDALONE
    run(lambda payload: reply(REAL_REFUSAL))
    assert catalog_projection.refresh_tool_names([name])["changed"] == 1
    assert catalog_projection.projection_payload(name)["shape"] == tool_shape.SHAPE_SKIN


def test_the_gadget_request_asks_for_english_tags_and_nothing_else():
    """The prompt is the only thing standing between a shape rule and a lane
    that rejects every non-English wiki.

    Asserted on the request this module would really send, not on
    `build_gadget_prompt` alone: the system turn carries the English
    instruction and the user turn carries the description, and a change that
    moved one without the other would still pass a test of either half.
    """
    payload = enrichment.payload_for(
        "m",
        Candidate("g", 1, "ab.wikipedia.org", "markblocked", RU_DESCRIPTION, "f", LANE_GADGET, GADGET_FIELDS),
    )
    _system, user = (message["content"] for message in payload["messages"])
    # The instruction travels with the keywords fragment now rather than sitting
    # in a lane's system prompt, so it reaches every lane that asks for the field.
    assert "English" in user
    assert '"keywords"' in user
    # The requested key, not the word: the prompt says "the description a wiki
    # shows" because that is the input it is handing over.
    assert '"description"' not in user
    assert RU_DESCRIPTION in user
    # A gadget answer is eight short tags; the user-script ceiling has to hold
    # three sentences as well, and paying for that here would be waste.
    full = enrichment.payload_for("m", Candidate("s", 1, ENWIKI, "t", BODY, "f", enrichment.LANE_USER_SCRIPT, SCRIPT_FIELDS))
    assert payload["max_tokens"] < full["max_tokens"]


def test_the_gadget_window_stops_at_the_limit():
    """A wave is `concurrency()` calls; a window that ignored `limit` would read
    the whole inventory into memory to ask about six of them."""
    for index in range(4):
        gadget(f"gadget{index}")
    with db.session_scope() as session:
        assert len(enrichment.gadget_pending(session, limit=2)) == 2


def test_each_lane_is_counted_against_its_own_denominator():
    """A tally of the whole table under a user-script denominator is a lie.

    `by_status` counted every row and `eligiblePages` counted user-script pages
    only, so the first gadget answered would have moved `ready` toward a number
    larger than the pages it is measured against -- and a lane 83% read would
    have looked finished. The same failure the docstring already describes,
    running the other way.
    """
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    store_gadget_inference()
    counts = enrichment.coverage()
    assert counts["ready"] == 1
    assert counts["gadgetsReady"] == 1
    assert counts["eligiblePages"] == 1
    assert counts["gadgetsEligible"] == 1


def test_a_ready_gadget_row_carrying_no_payload_publishes_nothing():
    """`ready` with an empty payload is possible and must stay silent.

    The status says the model was asked and answered; the payload says nothing
    survived shape validation. Publishing an empty keyword list would put a
    source in the evidence panel that contributed no value, and `_assemble`
    would credit it for a field it never filled.
    """
    gadget_id = gadget()
    with db.session_scope() as session:
        session.add(
            ToolInference(
                tool_name=GADGET_TOOL,
                payload={},
                lane=LANE_GADGET,
                page_id=gadget_id,
                source_fingerprint=enrichment.description_fingerprint(RU_DESCRIPTION),
                status=enrichment.STATUS_READY,
            )
        )
    assert sources_for(GADGET_TOOL) == {}


def test_a_gadget_keyword_records_which_text_the_model_read():
    """Both lanes publish under `llm_inference`, so the source alone cannot say.

    Without the lane the tool page tells roughly 10,000 gadget keywords they
    were read off source code -- and `wiki_gadgets` stores none to read.
    """
    store_gadget_inference(keywords=("clipboard",))
    sources = sources_for(GADGET_TOOL)[GADGET_TOOL]
    _record, evidence, _validation, _times = catalog_projection._assemble(GADGET_TOOL, sources)
    entry = evidence["keywords"][0]
    assert entry["source"] == catalog_projection.SOURCE_INFERENCE
    assert entry["lane"] == LANE_GADGET


def test_a_user_script_keyword_records_no_lane():
    """Absent rather than defaulted, so rows written before this keep their shape."""
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    sources = sources_for(TOOL)[TOOL]
    _record, evidence, _validation, _times = catalog_projection._assemble(TOOL, sources)
    assert all("lane" not in entry for entry in evidence["keywords"])


# --- audiences -------------------------------------------------------------
#
# Lift Wing, llm-qwen36-27b, 2026-09-05, through this module's own gadget prompt
# once `audiences` was added to it. Kept verbatim for the reason the other
# fixtures are: what is being tested is that asking for a second field did not
# cost the first, and a reply composed here could not show that.
REAL_COMBINED_REPLY = (
    '{"keywords": ["categories", "editing", "categorization", "wiki", "maintenance", '
    '"speed", "management", "tags"], "audiences": ["editor"]}'
)
# The same prompt for a gadget that adds an [archive] link beside external links.
REAL_COMBINED_REPLY_TWO = (
    '{"keywords": ["archives", "external links", "web archive", "citation", "references", '
    '"link rot", "internet archive", "preservation"], "audiences": ["reader", "editor"]}'
)


def test_asking_for_an_audience_did_not_cost_the_keywords():
    """Both fields come back from one real reply, and both survive validation."""
    accepted = enrichment.accept(enrichment.parse_json(REAL_COMBINED_REPLY), GADGET_FIELDS)
    assert accepted["audiences"] == ["editor"]
    assert len(accepted["keywords"]) == enrichment.MAX_KEYWORDS
    second = enrichment.accept(enrichment.parse_json(REAL_COMBINED_REPLY_TWO), GADGET_FIELDS)
    assert second["audiences"] == ["reader", "editor"]


def test_only_the_audiences_that_survived_being_counted_are_published():
    """Measured against 210 human-labelled tools: researcher 0.36, admin 0.38, organizer 0.42.

    Publishing those would put a wrong audience on roughly three records in five
    that carry one. The three that stay are 149/171 correct together.
    """
    verdict = enrichment._audiences(["editor", "researcher", "admin", "organizer", "reader"])
    assert verdict.value == ["editor", "reader"]


def test_an_answer_this_catalogue_does_not_publish_is_not_recorded_as_a_failure():
    """`researcher` is a correct reading of some tools and simply is not published.

    Recording a reason would file it as the model having broken a rule, and the
    rejection backfill would then re-ask a question that was answered properly.
    """
    verdict = enrichment._audiences(["researcher"])
    assert verdict.value == []
    assert verdict.reason == ""


def test_an_audience_outside_the_vocabulary_is_a_malformed_answer():
    """Ignoring the list it was handed is a different fault, and is reported."""
    verdict = enrichment._audiences(["wizard", "editor"])
    assert verdict.value == ["editor"]
    assert enrichment._audiences(["wizard"]).reason


def test_both_prompts_offer_the_whole_vocabulary_not_just_what_is_published():
    """Offering only the publishable three is what made them worse.

    Asked with the short list, the model puts a research or moderation tool on
    the nearest survivor rather than declining: developer fell from 0.86 to 0.76
    and reader from 0.80 to 0.74. The unpublished values earn their place in the
    prompt by giving those tools somewhere else to go.
    """
    for lane in (LANE_GADGET, enrichment.LANE_USER_SCRIPT):
        fields = enrichment.lane_fields(lane)
        prompt = enrichment.payload_for(
            "m", Candidate("x", 1, ENWIKI, "t", BODY, "f", lane, fields)
        )["messages"][1]["content"]
        for value in enrichment.AUDIENCE_VOCABULARY:
            assert f'"{value}"' in prompt, f"{lane} prompt does not offer {value}"


def test_a_gadget_audience_reaches_the_projection_and_fills_a_gap():
    """All 11,012 gadget records and all 40,254 user scripts have no audience at all.

    `audiences` is a list field, so `FILL_ONLY_SOURCES` already stops this from
    extending one somebody else wrote -- the gap is the whole population.
    """
    gadget_id = gadget()
    with db.session_scope() as session:
        session.add(
            ToolInference(
                tool_name=GADGET_TOOL,
                payload={"audiences": ["editor"]},
                lane=LANE_GADGET,
                page_id=gadget_id,
                source_fingerprint=enrichment.description_fingerprint(RU_DESCRIPTION),
                status=enrichment.STATUS_READY,
            )
        )
    sources = sources_for(GADGET_TOOL)[GADGET_TOOL]
    record, evidence, _validation, _times = catalog_projection._assemble(GADGET_TOOL, sources)
    assert record["audiences"] == ["editor"]
    assert evidence["audiences"][0]["source"] == catalog_projection.SOURCE_INFERENCE
    assert evidence["audiences"][0]["lane"] == LANE_GADGET


def test_an_audiences_value_that_is_not_a_list_is_refused_by_shape():
    """The same rule keywords get: a model answering with prose is malformed."""
    verdict = enrichment._audiences("editor")
    assert verdict.value == []
    assert "not a list" in verdict.reason


def test_no_more_audiences_are_published_than_a_record_can_usefully_carry():
    """Three is the whole publishable vocabulary, so a fourth could only repeat one."""
    verdict = enrichment._audiences(["editor", "developer", "reader", "editor", "developer"])
    assert verdict.value == ["editor", "developer", "reader"]
    assert len(verdict.value) == enrichment.MAX_AUDIENCES


def test_a_gadget_answered_by_an_older_prompt_is_asked_again():
    """A fingerprint says the source has not moved, not that the answer is complete.

    `audiences` shipped to 9,946 gadget rows that sat `ready` and audience-less,
    every one current on its fingerprint, and no window would have offered them
    again. This is the arm that reaches them.
    """
    gadget_id = gadget()
    with db.session_scope() as session:
        session.add(
            ToolInference(
                tool_name=GADGET_TOOL,
                payload={"keywords": ["block"]},
                lane=LANE_GADGET,
                page_id=gadget_id,
                source_fingerprint=enrichment.description_fingerprint(RU_DESCRIPTION),
                status=enrichment.STATUS_READY,
                asked_signature="keywords",
            )
        )
    with db.session_scope() as session:
        assert [c.title for c in enrichment.gadget_pending(session, limit=10)] == ["markblocked"]


def test_a_user_script_answered_by_an_older_prompt_is_asked_again():
    """The same arm on the lane that holds 36,545 of those rows."""
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    with db.session_scope() as session:
        assert enrichment.pending(session, limit=10) == []
        session.query(ToolInference).update({"asked_signature": "description,keywords"})
    with db.session_scope() as session:
        assert [c.tool_name for c in enrichment.pending(session, limit=10)] == [TOOL]


def test_answering_again_records_the_prompt_that_answered():
    """Or the row is offered every sweep for ever, and the backfill never drains."""
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_WHOLE_REPLY))
    with db.session_scope() as session:
        row = session.get(ToolInference, TOOL)
        assert row.asked_signature == enrichment.lane_signature(enrichment.LANE_USER_SCRIPT)
        assert enrichment.pending(session, limit=10) == []


def test_a_re_ask_waits_behind_pages_nobody_has_tried(monkeypatch):
    """46,491 rows to re-ask must not displace a page that has never been asked at all."""
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    with db.session_scope() as session:
        session.query(ToolInference).update({"asked_signature": "description,keywords"})
    store("User:Someone/fresh.js", owner="Someone", basename="fresh.js", fingerprint="f2")
    with db.session_scope() as session:
        order = [c.tool_name for c in enrichment.pending(session, limit=10)]
    assert order[0] == "userscript-en.wikipedia.org-someone-fresh.js", order


# --- composing a prompt from what a row is missing ---------------------------


def test_a_backfill_asks_only_for_the_field_it_went_back_for():
    """The point of composing: a re-ask is charged for one question, not three.

    A row that already holds a description and keywords is missing only
    `audiences`, and the source has not moved -- so regenerating three
    sentences to collect one array is most of the cost of the call for none of
    the value.
    """
    candidate = Candidate("t", 1, ENWIKI, "User:X/t.js", BODY, "f", enrichment.LANE_USER_SCRIPT, ("audiences",))
    payload = enrichment.payload_for("m", candidate)
    user = payload["messages"][1]["content"]
    assert '"audiences"' in user
    assert '"description"' not in user
    assert '"keywords"' not in user
    full = enrichment.payload_for("m", candidate._replace(fields=SCRIPT_FIELDS))
    assert payload["max_tokens"] < full["max_tokens"]


def test_a_new_field_is_missing_from_every_row_that_predates_it():
    """The property the whole design exists for: adding a field is adding a field.

    No version to bump and no migration to remember -- a row records which
    questions it has been put, so one it has never been put is missing the
    moment the field joins `FIELD_ORDER`.
    """
    lane = enrichment.LANE_USER_SCRIPT
    complete = enrichment.lane_signature(lane)
    assert enrichment.missing_fields(lane, complete) == ()
    extra = enrichment.Field("license", enrichment._keywords, enrichment._keywords_request, 50, frozenset({lane}))
    with mock.patch.object(enrichment, "FIELD_ORDER", (*enrichment.FIELD_ORDER, extra)), mock.patch.dict(
        enrichment.FIELDS_BY_NAME, {"license": extra}
    ):
        assert enrichment.missing_fields(lane, complete) == ("license",)


def test_a_field_a_lane_cannot_produce_is_never_missing_from_it():
    """A gadget already has a maintainer's description, so it is never asked for one."""
    assert "description" not in enrichment.lane_fields(LANE_GADGET)
    assert "description" not in enrichment.missing_fields(LANE_GADGET, "")


def test_answering_one_field_keeps_the_answers_already_stored():
    """A merge, not a replacement -- or the backfill destroys what it went back to complete."""
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
    with db.session_scope() as session:
        before = dict(session.get(ToolInference, TOOL).payload)
        session.query(ToolInference).update({"asked_signature": "description,keywords"})
    assert "description" in before and "keywords" in before

    with db.session_scope() as session:
        pending = enrichment.pending(session, limit=5)
        assert [c.fields for c in pending] == [("audiences",)]
        wave = enrichment.with_source(session, pending)
    with db.session_scope() as session:
        outcome = enrichment._ask(wave[0], lambda payload: reply('{"audiences": ["editor"]}'), model="m")
        enrichment.record(session, wave[0], outcome, model="m")
    with db.session_scope() as session:
        row = session.get(ToolInference, TOOL)
    assert row.payload["description"] == before["description"], "the re-ask dropped the description"
    assert row.payload["keywords"] == before["keywords"]
    assert row.payload["audiences"] == ["editor"]
    assert row.asked_signature == enrichment.lane_signature(enrichment.LANE_USER_SCRIPT)


def test_a_field_the_model_declined_is_not_asked_again_on_the_same_source():
    """Declining is an answer. The signature records the question, not the result.

    Keyed on what was asked rather than what came back, because `accept` stores
    nothing for a field that produced nothing -- so a payload cannot tell a
    declined field from an unasked one, and a window that read the payload would
    re-ask the same unanswerable page every sweep for ever.
    """
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply('{"description": null, "keywords": [], "audiences": []}'))
    with db.session_scope() as session:
        row = session.get(ToolInference, TOOL)
        assert row.payload == {}
        assert row.asked_signature == enrichment.lane_signature(enrichment.LANE_USER_SCRIPT)
        assert enrichment.pending(session, limit=5) == []


def test_a_prompt_that_would_ask_nothing_is_refused_rather_than_sent():
    """A row with nothing missing must never reach the endpoint.

    It would be a request with no question in it, and the model would answer
    something -- billing a Lift Wing call to learn nothing. The windows already
    fall back to the lane's whole set rather than an empty one, so reaching here
    means a caller built a candidate by hand and got it wrong; saying so beats
    sending it.
    """
    with pytest.raises(ValueError, match="asking nothing"):
        enrichment.build_prompt(enrichment.LANE_USER_SCRIPT, ENWIKI, "User:X/t.js", BODY, ())
