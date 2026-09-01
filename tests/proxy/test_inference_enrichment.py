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
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import catalog_projection, db, run_budget, userscripts  # noqa: E402
from backend import inference_enrichment as enrichment  # noqa: E402
from backend.models import ToolInference, UserScriptDirectoryEntry, UserScriptPage, utcnow  # noqa: E402

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


def test_a_refusal_records_which_field_refused_and_why():
    # 4,253 rejections were stored with an empty `detail`, so the only way to
    # learn why the lane produced nothing was to re-ask the model.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REFUSAL))
    assert details()[TOOL] == "description: absent or null in the reply; keywords: empty list"


def test_a_description_that_fails_while_keywords_pass_is_ready_and_still_says_what_is_missing():
    # `accept` returns the fields that survived, so one surviving keyword makes
    # the row `ready` with no description at all. Without the reason recorded
    # here, that row is indistinguishable from a described tool in every count.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply('{"description": "Too short.", "keywords": ["links"]}'))
    assert rows()[TOOL][0] == enrichment.STATUS_READY
    assert "description" not in rows()[TOOL][1]
    assert details()[TOOL] == "description: 10 chars, wanted 20-600"


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
    # does not already hold -- and this table is 37,791 rows wide.
    store("User:Anomie/linkclassifier.js")
    run(lambda payload: reply(REAL_REPLY))
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
    assert enrichment.check({"description": value}).get("description").reason.startswith("not a string")


def test_a_description_carrying_a_link_is_refused():
    # A description is rendered on the tool page. A URL the model invented
    # there is a link this site would be publishing on somebody else's behalf.
    verdict = enrichment.check({"description": "A gadget documented at https://example.invalid/docs page."})
    assert verdict["description"] == enrichment.Checked("", "contains a URL")


def test_keywords_offered_as_anything_but_a_list_are_refused_by_type():
    assert enrichment.check({"keywords": "links, css"})["keywords"].reason == "not a list (str)"


def test_a_keyword_list_mixing_prose_and_junk_keeps_only_the_strings():
    accepted = enrichment.accept({"keywords": ["links", 7, None, {"tag": "css"}, "css"]})

    assert accepted["keywords"] == ["links", "css"]


def test_a_reply_that_parsed_to_nothing_stores_nothing():
    # `accept` is the last gate before a value is written under a person's
    # name, so it has to hold for the empty reply as well as the bad one.
    assert enrichment.accept(None) == {}
    assert enrichment.accept({}) == {}


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
