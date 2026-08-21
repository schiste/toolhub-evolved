# SPDX-License-Identifier: GPL-3.0-or-later
"""Asking a MediaWiki for a page set, and reading what comes back."""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import wiki_api, wiki_sources  # noqa: E402

DOMAIN = "en.wikipedia.org"


def _params(url):
    parsed = urlparse(url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == ("https", DOMAIN, "/w/api.php")
    return {key: value[0] for key, value in parse_qs(parsed.query).items()}


def _page(title, revid=1, timestamp="2024-01-01T00:00:00Z", content="x"):
    return {
        "pageid": abs(hash(title)) % 10000,
        "ns": 2,
        "title": title,
        "revisions": [{"revid": revid, "timestamp": timestamp, "slots": {"main": {"content": content}}}],
    }


def _payload(*pages):
    return {"batchcomplete": True, "query": {"pages": list(pages)}}


# --- queries -----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        wiki_api.definition_url(DOMAIN),
        wiki_api.pages_url(DOMAIN, ("User:E/t.js",)),
        wiki_api.subpages_url(DOMAIN, 2, "E/t"),
    ],
)
def test_every_query_is_polite_and_uses_the_modern_response_shape(url):
    params = _params(url)
    # maxlag lets the wiki shed a background reader first when its replicas
    # fall behind, which is what "do not max out requests" looks like here.
    assert params["maxlag"] == str(wiki_api.MAXLAG_SECONDS)
    # formatversion 2 is what makes query.pages a list rather than a mapping
    # keyed by page id, which is the shape the parser below expects.
    assert params["formatversion"] == "2"
    assert params["action"] == "query"


def _answer(url, content):
    """Build the payload a wiki returns for this query, honouring its rvprop.

    Fixtures that hand the parser fields the query never asked for cannot see a
    request and its parser drift apart, which is exactly what happened here.
    """
    asked = set(_params(url)["rvprop"].split("|"))
    revision = {"slots": {"main": {"content": content}}}
    if "ids" in asked:
        revision["revid"] = 7
    if "timestamp" in asked:
        revision["timestamp"] = "2024-01-01T00:00:00Z"
    page = {"pageid": 1, "ns": 8, "title": wiki_sources.GADGET_DEFINITION_TITLE, "revisions": [revision]}
    return {"batchcomplete": True, "query": {"pages": [page]}}


def test_the_definition_query_asks_for_what_its_own_parser_requires():
    url = wiki_api.definition_url(DOMAIN)
    assert _params(url)["titles"] == wiki_sources.GADGET_DEFINITION_TITLE
    # The regression: rvprop=content returns revisions with no revid, _revision
    # drops those, and so every definition page on every wiki read as empty.
    assert wiki_api.definition_text(_answer(url, "* X[RL]|X.js")) == "* X[RL]|X.js"


def test_the_definition_query_asks_for_no_more_than_that():
    # The id is a parser requirement, not a want. Nothing reads it: keeping the
    # definition page out of tool heads is definition_text's job, and it
    # returns wikitext only.
    assert _params(wiki_api.definition_url(DOMAIN))["rvprop"] == "ids|content"


def test_a_page_query_asks_for_every_title_at_once():
    params = _params(wiki_api.pages_url(DOMAIN, ("MediaWiki:Gadget-A.js", "MediaWiki:Gadget-B.css")))
    assert params["titles"] == "MediaWiki:Gadget-A.js|MediaWiki:Gadget-B.css"
    assert params["rvprop"] == "ids|timestamp|content"
    # Content lives in a slot; asking without naming it returns no text.
    assert params["rvslots"] == "main"


def test_a_page_query_never_exceeds_the_api_title_limit():
    titles = tuple(f"User:E/t/p{index}.js" for index in range(wiki_api.wiki_sources.MAX_PAGES * 3))
    assert _params(wiki_api.pages_url(DOMAIN, titles))["titles"].count("|") == wiki_sources.MAX_PAGES - 1


def test_a_subpage_query_discovers_and_reads_in_one_request():
    params = _params(wiki_api.subpages_url(DOMAIN, 2, "Example/twinkle"))
    # The generator feeds the prefix search straight into the revision fetch,
    # so discovery costs no request of its own.
    assert params["generator"] == "allpages"
    assert (params["gapnamespace"], params["gapprefix"]) == ("2", "Example/twinkle")
    assert params["gaplimit"] == str(wiki_sources.MAX_PAGES)
    assert params["rvprop"] == "ids|timestamp|content"


def test_a_title_with_a_reserved_character_survives_the_query_string():
    assert _params(wiki_api.pages_url(DOMAIN, ("User:E/a b&c.js",)))["titles"] == "User:E/a b&c.js"


# --- errors ------------------------------------------------------------------


def test_an_api_error_arrives_as_a_normal_response_and_is_still_an_error():
    # The Action API answers HTTP 200 with an error object. A caller that only
    # checked the status would read this as "the tool has no source".
    assert wiki_api.api_error({"error": {"code": "maxlag", "info": "Waiting for a replica"}}) == "maxlag"


@pytest.mark.parametrize("payload", [{}, {"query": {"pages": []}}, {"error": None}, "not an object", None])
def test_a_normal_response_reports_no_error(payload):
    assert wiki_api.api_error(payload) == ""


def test_an_error_code_is_bounded():
    assert len(wiki_api.api_error({"error": {"code": "x" * 500}})) == 64


# --- parsing -----------------------------------------------------------------


def test_a_page_set_is_read_back_with_its_content_and_revision_ids():
    found = wiki_api.revisions(_payload(_page("User:E/t.js", revid=42, content="var a = 1;")))
    assert len(found) == 1
    assert (found[0].title, found[0].revision_id, found[0].content) == ("User:E/t.js", 42, "var a = 1;")
    assert found[0].edited_at == "2024-01-01T00:00:00Z"


def test_pages_come_back_in_title_order_whatever_order_the_api_used():
    # The API returns pages in whatever order its indexes produce. A set that
    # hashed differently on each poll would rescan the tool forever.
    forward = wiki_api.revisions(_payload(_page("User:E/t.js"), _page("User:E/t.css")))
    backward = wiki_api.revisions(_payload(_page("User:E/t.css"), _page("User:E/t.js")))
    assert [revision.title for revision in forward] == ["User:E/t.css", "User:E/t.js"]
    assert forward == backward


def test_a_title_the_wiki_has_no_page_for_is_an_answer_not_a_failure():
    # A gadget definition can name a file nobody ever created.
    payload = _payload(_page("MediaWiki:Gadget-A.js"), {"ns": 8, "title": "MediaWiki:Gadget-Gone.js", "missing": True})
    assert [revision.title for revision in wiki_api.revisions(payload)] == ["MediaWiki:Gadget-A.js"]


@pytest.mark.parametrize(
    "revision",
    [
        # No slot content: the page exists but the query did not return text.
        {"revid": 1, "slots": {}},
        {"revid": 1, "slots": {"main": {"texthidden": True}}},
        # A revision id that is not one. True would otherwise pass an int check.
        {"revid": True, "slots": {"main": {"content": "x"}}},
        {"revid": "42", "slots": {"main": {"content": "x"}}},
    ],
)
def test_a_revision_that_is_missing_what_it_needs_is_dropped(revision):
    payload = _payload({"ns": 2, "title": "User:E/t.js", "revisions": [revision]})
    assert wiki_api.revisions(payload) == ()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        "not an object",
        {"query": {}},
        {"query": {"pages": "not a list"}},
        {"query": {"pages": ["not an object"]}},
        {"query": {"pages": [{"ns": 2, "revisions": [{"revid": 1}]}]}},
        {"query": {"pages": [{"title": "User:E/t.js", "revisions": []}]}},
        {"query": {"pages": [{"title": "User:E/t.js", "revisions": "no"}]}},
    ],
)
def test_payload_shapes_that_yield_no_revisions(payload):
    assert wiki_api.revisions(payload) == ()


def test_page_content_is_bounded():
    payload = _payload(_page("User:E/t.js", content="x" * (wiki_api.MAX_CONTENT_CHARS * 2)))
    assert len(wiki_api.revisions(payload)[0].content) == wiki_api.MAX_CONTENT_CHARS


def test_definition_text_is_the_wikitext_of_the_one_page_asked_for():
    assert wiki_api.definition_text(_payload(_page(wiki_sources.GADGET_DEFINITION_TITLE, content="* X[RL]|X.js"))) == (
        "* X[RL]|X.js"
    )


def test_a_wiki_with_no_gadget_definitions_reads_as_empty_not_as_an_error():
    assert (
        wiki_api.definition_text({"query": {"pages": [{"title": "MediaWiki:Gadgets-definition", "missing": True}]}})
        == ""
    )


# --- head --------------------------------------------------------------------


def test_the_head_covers_the_whole_set_not_just_the_entry_page():
    # A gadget whose main file is untouched but whose helper was rewritten has
    # changed. A head tracking only the page we were pointed at would never
    # rescan it.
    before = wiki_api.revisions(
        _payload(_page("MediaWiki:Gadget-A.js", revid=1), _page("MediaWiki:Gadget-B.js", revid=7))
    )
    after = wiki_api.revisions(
        _payload(_page("MediaWiki:Gadget-A.js", revid=1), _page("MediaWiki:Gadget-B.js", revid=8))
    )
    assert wiki_api.head(before) != wiki_api.head(after)


def test_the_head_ignores_content_and_timestamps_so_a_null_edit_is_not_a_change():
    same = wiki_api.head(
        wiki_api.revisions(_payload(_page("User:E/t.js", revid=5, content="a", timestamp="2020-01-01T00:00:00Z")))
    )
    assert same == wiki_api.head(
        wiki_api.revisions(_payload(_page("User:E/t.js", revid=5, content="b", timestamp="2024-01-01T00:00:00Z")))
    )


def test_the_head_is_shaped_like_the_commit_sha_it_stands_in_for():
    import repository_scan

    assert repository_scan.SHA_RE.fullmatch(wiki_api.head(wiki_api.revisions(_payload(_page("User:E/t.js")))))


def test_an_empty_set_still_has_a_head():
    # Not a crash and not an empty string: an empty set is a real state that
    # must compare unequal to any non-empty one.
    assert wiki_api.head(()) != wiki_api.head(wiki_api.revisions(_payload(_page("User:E/t.js"))))


# --- timestamps --------------------------------------------------------------


def test_the_set_is_dated_by_its_most_recent_edit():
    found = wiki_api.revisions(
        _payload(
            _page("User:E/t.js", timestamp="2020-05-01T00:00:00Z"),
            _page("User:E/t.css", timestamp="2024-09-01T00:00:00Z"),
        )
    )
    assert wiki_api.last_edited_at(found) == "2024-09-01T00:00:00Z"


def test_a_set_with_no_readable_timestamp_is_undated_rather_than_epoch():
    found = wiki_api.revisions(_payload(_page("User:E/t.js", timestamp="")))
    assert wiki_api.last_edited_at(found) == ""
    assert wiki_api.last_edited_at(()) == ""
