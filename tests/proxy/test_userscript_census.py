"""Finding and reading a wiki's user scripts through the public API.

The payload shapes here are the ones fr.wikipedia.org actually returns, and the
two limits that shape the module are real: search refuses an offset of 10,000
(`cirrussearch-offset-too-large`, observed), and frwiki holds 9,345 javascript
and 4,270 css pages in user space -- close enough to the cap that the module has
to say so rather than stop quietly.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import userscript_census as census  # noqa: E402


def searcher(total, pages):
    """A stand-in for one search endpoint, recording the offsets it was asked for."""
    calls = []

    def search(query, offset):
        calls.append((query, offset))
        return (total, pages.pop(0) if pages else [])

    return search, calls


def revision(title, *, model="javascript", content="x", **extra):
    return {
        "title": title,
        "revisions": [
            {"revid": 1, "timestamp": "2026-01-01T00:00:00Z", "slots": {"main": {"contentmodel": model, "content": content}}},
        ],
        **extra,
    }


# --- the query -------------------------------------------------------------


def test_the_query_asks_for_a_content_model_not_a_suffix():
    assert census.search_query("javascript") == "contentmodel:javascript"


def test_a_prefix_narrows_the_query():
    # How a wiki too large for one walk gets split into walkable pieces.
    assert census.search_query("css", prefix="User:A") == "contentmodel:css prefix:User:A"


def test_search_params_omit_the_offset_on_the_first_page():
    assert "sroffset" not in census.search_params("contentmodel:javascript", 0)


def test_search_params_carry_a_later_offset():
    assert census.search_params("contentmodel:javascript", 500)["sroffset"] == 500


def test_the_search_is_confined_to_user_space():
    assert census.search_params("contentmodel:javascript", 0)["srnamespace"] == 2


# --- walking the index -----------------------------------------------------


def test_one_page_of_results_completes_the_walk():
    search, calls = searcher(2, [["User:A/x.js", "User:B/y.js"]])
    found = census.enumerate_titles(search, "javascript")
    assert found.titles == ("User:A/x.js", "User:B/y.js")
    assert found.complete is True
    assert len(calls) == 1


def test_the_walk_continues_until_every_hit_is_read():
    search, calls = searcher(4, [["a", "b"], ["c", "d"]])
    found = census.enumerate_titles(search, "javascript")
    assert found.titles == ("a", "b", "c", "d")
    assert [offset for _query, offset in calls] == [0, 2]


def test_a_wiki_larger_than_the_offset_cap_is_reported_not_truncated():
    # 10,000 is where CirrusSearch refuses. Returning the first page as though
    # it were the whole wiki is the failure this exists to prevent.
    search, _calls = searcher(45_000, [["User:A/x.js"]])
    found = census.enumerate_titles(search, "javascript")
    assert found.complete is False
    assert found.total == 45_000


def test_a_short_answer_stops_the_walk_rather_than_looping():
    # A count that disagrees with what the index will hand over must not spin.
    search, calls = searcher(9, [["a"], []])
    found = census.enumerate_titles(search, "javascript")
    assert found.titles == ("a",)
    assert len(calls) == 2


def test_a_wiki_with_no_pages_of_the_model_walks_cleanly():
    search, _calls = searcher(0, [[]])
    found = census.enumerate_titles(search, "css")
    assert found.titles == ()
    assert found.complete is True


def test_the_walk_carries_its_prefix_into_every_request():
    search, calls = searcher(3, [["a", "b"], ["c"]])
    census.enumerate_titles(search, "javascript", prefix="User:A")
    assert {query for query, _offset in calls} == {"contentmodel:javascript prefix:User:A"}


def test_reading_a_search_answer():
    payload = {
        "query": {
            "searchinfo": {"totalhits": 9345},
            "search": [{"ns": 2, "title": "Utilisateur:Arkanosis/xpatrol.js", "pageid": 4229263}],
        },
    }
    assert census.read_search(payload) == (9345, ("Utilisateur:Arkanosis/xpatrol.js",))


def test_a_search_answer_with_no_query_reads_as_empty():
    assert census.read_search({"batchcomplete": True}) == (0, ())


def test_a_search_answer_with_no_hit_count_still_reads_its_results():
    assert census.read_search({"query": {"search": [{"title": "a"}]}}) == (0, ("a",))


def test_a_search_answer_with_no_result_list_reads_its_hit_count():
    assert census.read_search({"query": {"searchinfo": {"totalhits": 7}}}) == (7, ())


def test_a_malformed_search_result_is_skipped():
    payload = {"query": {"searchinfo": {"totalhits": 2}, "search": [{"title": "a"}, "junk"]}}
    assert census.read_search(payload) == (2, ("a",))


# --- reading pages ---------------------------------------------------------


def test_batches_cover_every_title():
    titles = [f"User:U{index}/x.js" for index in range(45)]
    batches = list(census.batched(titles, size=20))
    assert [len(batch) for batch in batches] == [20, 20, 5]
    assert [title for batch in batches for title in batch] == titles


def test_an_empty_corpus_produces_no_batches():
    assert list(census.batched([])) == []


def test_content_params_ask_for_the_main_slot():
    params = census.content_params(["User:A/x.js", "User:B/y.js"])
    assert params["rvslots"] == "main"
    assert params["titles"] == "User:A/x.js|User:B/y.js"


def test_reading_a_page_keeps_its_model_and_source():
    payload = {"query": {"pages": [revision("Utilisateur:Arkanosis/xpatrol.js", content="var x = 1;")]}}
    (page,) = census.read_pages(payload)
    assert (page.title, page.model, page.body) == ("Utilisateur:Arkanosis/xpatrol.js", "javascript", "var x = 1;")
    assert (page.revision, page.touched) == ("1", "2026-01-01T00:00:00Z")


def test_a_css_page_holding_javascript_reports_the_model_the_wiki_recorded():
    # User:Penquista/monobook.css is this page. The suffix says css; MediaWiki
    # parses it as javascript, and the model is what the directory must believe.
    payload = {"query": {"pages": [revision("User:Penquista/monobook.css", model="javascript")]}}
    (page,) = census.read_pages(payload)
    assert page.model == "javascript"


def test_a_page_deleted_between_discovery_and_fetch_is_skipped():
    # An ordinary event in a census that runs for minutes over a live wiki.
    payload = {"query": {"pages": [{"title": "User:Gone/x.js", "missing": True}, revision("User:A/x.js")]}}
    assert [page.title for page in census.read_pages(payload)] == ["User:A/x.js"]


def test_an_invalid_title_is_skipped():
    payload = {"query": {"pages": [{"title": "User:<>/x.js", "invalid": True}]}}
    assert census.read_pages(payload) == ()


def test_a_page_with_no_revisions_is_skipped():
    assert census.read_pages({"query": {"pages": [{"title": "User:A/x.js"}]}}) == ()


def test_a_page_whose_revisions_are_not_a_list_is_skipped():
    assert census.read_pages({"query": {"pages": [{"title": "a", "revisions": {}}]}}) == ()


def test_a_page_with_an_empty_revision_list_is_skipped():
    assert census.read_pages({"query": {"pages": [{"title": "a", "revisions": []}]}}) == ()


def test_a_revision_that_is_not_an_object_is_skipped():
    assert census.read_pages({"query": {"pages": [{"title": "a", "revisions": ["junk"]}]}}) == ()


def test_a_revision_with_no_main_slot_is_skipped():
    assert census.read_pages({"query": {"pages": [{"title": "a", "revisions": [{"slots": {}}]}]}}) == ()


def test_a_revision_with_no_slots_at_all_is_skipped():
    assert census.read_pages({"query": {"pages": [{"title": "a", "revisions": [{"revid": 1}]}]}}) == ()


def test_a_page_entry_that_is_not_an_object_is_skipped():
    assert census.read_pages({"query": {"pages": ["junk"]}}) == ()


def test_an_answer_with_no_pages_reads_as_empty():
    assert census.read_pages({"query": {}}) == ()


def test_an_answer_that_is_not_an_object_reads_as_empty():
    assert census.read_pages("junk") == ()


def test_an_answer_whose_query_is_not_an_object_reads_as_empty():
    assert census.read_pages({"query": "junk"}) == ()


def test_an_empty_page_body_is_still_a_page():
    # 1,045 frwiki user-space JS pages are empty. They are not fetch failures.
    payload = {"query": {"pages": [revision("User:A/x.js", content="")]}}
    (page,) = census.read_pages(payload)
    assert page.body == ""


# --- watching for changes --------------------------------------------------


def test_a_user_space_script_is_worth_fetching():
    assert census.is_script_page("Utilisateur:Arkanosis/xpatrol.js", 2) is True


def test_a_user_space_stylesheet_is_worth_fetching():
    assert census.is_script_page("User:A/vector.css", 2) is True


def test_an_uppercase_suffix_still_counts():
    assert census.is_script_page("User:A/Monobook.JS", 2) is True


def test_an_ordinary_user_page_is_not_worth_fetching():
    assert census.is_script_page("Utilisateur:Johan Pekanmäki", 2) is False


def test_a_script_outside_user_space_is_not_this_censuss_business():
    assert census.is_script_page("MediaWiki:Gadget-Popups.js", 8) is False


def test_changes_ask_for_edits_as_well_as_new_pages():
    # A script rewritten this morning changes the directory exactly as much as
    # one created this morning.
    assert census.changes_params("", 500)["rctype"] == "new|edit"


def test_changes_start_from_the_last_run_when_there_was_one():
    assert census.changes_params("2026-08-01T00:00:00Z", 500)["rcstart"] == "2026-08-01T00:00:00Z"


def test_a_first_run_asks_for_no_start_point():
    assert "rcstart" not in census.changes_params("", 500)


def test_changes_are_read_oldest_first_so_a_run_can_resume():
    assert census.changes_params("", 500)["rcdir"] == "newer"


def test_only_script_pages_survive_the_change_feed():
    payload = {
        "query": {
            "recentchanges": [
                {"ns": 2, "title": "Utilisateur:Johan Pekanmäki", "timestamp": "2026-08-20T14:38:56Z"},
                {"ns": 2, "title": "Utilisateur:Zebulon84/common.js", "timestamp": "2026-08-20T14:33:27Z"},
                {"ns": 0, "title": "Paris", "timestamp": "2026-08-20T14:30:00Z"},
            ],
        },
    }
    assert census.read_changes(payload) == ("Utilisateur:Zebulon84/common.js",)


def test_a_page_edited_twice_is_fetched_once():
    payload = {
        "query": {
            "recentchanges": [
                {"ns": 2, "title": "User:A/x.js"},
                {"ns": 2, "title": "User:A/x.js"},
            ],
        },
    }
    assert census.read_changes(payload) == ("User:A/x.js",)


def test_a_malformed_change_is_skipped():
    payload = {"query": {"recentchanges": [{"ns": 2, "title": "User:A/x.js"}, "junk"]}}
    assert census.read_changes(payload) == ("User:A/x.js",)


def test_a_change_feed_with_no_list_reads_as_empty():
    assert census.read_changes({"query": {}}) == ()


def test_a_change_feed_that_is_not_an_object_reads_as_empty():
    assert census.read_changes("junk") == ()
