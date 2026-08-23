# SPDX-License-Identifier: GPL-3.0-or-later
"""Choosing which road names a wiki's script pages, and what each road promises.

No test here reaches a replica or a wiki. Both are injected, because the part
worth pinning is the choice between them and the shape of what comes back --
above all that the two roads agree on how a title is spelled, since the sweep
keys ranks, revisions and tombstones on exactly that string.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import userscript_enumeration as enumeration, wiki_replica  # noqa: E402

FRWIKI = "fr.wikipedia.org"
USER = wiki_replica.Credentials(user="s55555", password="sekrit")

#: What frwiki's replica holds, in page-id order, and what it calls user space.
REPLICA_ROWS = (
    ("javascript", "Tom_Smith/monobook.js", "101"),
    ("css", "Ada/vector.css", "102"),
    ("javascript", "Zoe/tools.js", "103"),
)


class FakeWiki:
    """An Action API that answers siteinfo and search, and counts what it was asked."""

    def __init__(self, *, prefix="Utilisateur", titles=(), total=None):
        self.prefix = prefix
        self.titles = list(titles)
        self.total = total
        self.requests = []

    def request(self, domain, method, params):
        self.requests.append(params)
        if params.get("meta") == "siteinfo":
            names = {"2": {"name": self.prefix}} if self.prefix else {}
            return {"query": {"namespaces": names}}
        model = params["srsearch"].split("contentmodel:", 1)[1]
        found = [title for kind, title in self.titles if kind == model]
        return {
            "query": {
                "searchinfo": {"totalhits": self.total if self.total is not None else len(found)},
                "search": [{"title": title} for title in found],
            },
        }


def replica(rows=REPLICA_ROWS, *, dbname="frwiki", fail=False):
    """Stand in for `wiki_replica`'s two reads, without a database."""

    def titles_for(_dbname, **_kwargs):
        if fail:
            raise RuntimeError("replica is down")
        return tuple(rows)

    def dbnames_for(_wikis, **_kwargs):
        if fail:
            raise RuntimeError("replica is down")
        return {FRWIKI: dbname} if dbname else {}

    return dbnames_for, titles_for


def with_replica(monkeypatch, rows=REPLICA_ROWS, *, dbname="frwiki", fail=False):
    dbnames_for, titles_for = replica(rows, dbname=dbname, fail=fail)
    monkeypatch.setattr(wiki_replica, "dbnames_for", dbnames_for)
    monkeypatch.setattr(wiki_replica, "script_titles_for", titles_for)


def enumerate_with(wiki, *, user=USER):
    return enumeration.enumerate_wiki(wiki.request, FRWIKI, credentials=lambda: user, connect=None)


# --- the replica road ------------------------------------------------------


def test_the_replica_names_every_page_in_the_order_it_was_created(monkeypatch):
    with_replica(monkeypatch)
    found = enumerate_with(FakeWiki())
    assert found.source == enumeration.SOURCE_REPLICA
    assert found.titles == (
        "Utilisateur:Tom Smith/monobook.js",
        "Utilisateur:Ada/vector.css",
        "Utilisateur:Zoe/tools.js",
    )


def test_a_replica_enumeration_is_complete_and_counts_each_model(monkeypatch):
    with_replica(monkeypatch)
    found = enumerate_with(FakeWiki())
    assert found.complete is True
    assert found.totals == {"javascript": 2, "css": 1}


def test_titles_are_spelled_the_way_the_wiki_itself_spells_them(monkeypatch):
    # The replica has no namespace name; asking the wiki is the only way to get
    # frwiki's `Utilisateur:` rather than the canonical `User:`. Building the
    # wrong one would make every stored page look unknown, and a sweep that
    # believes it has seen every page tombstones the ones it did not recognise.
    with_replica(monkeypatch)
    assert all(title.startswith("Utilisateur:") for title in enumerate_with(FakeWiki()).titles)


def test_underscores_from_the_replica_become_the_spaces_the_api_answers_with(monkeypatch):
    with_replica(monkeypatch, (("javascript", "Tom_Smith/monobook.js", "101"),))
    assert enumerate_with(FakeWiki()).titles == ("Utilisateur:Tom Smith/monobook.js",)


def test_the_replica_hands_back_the_current_revision_of_every_page_it_names(monkeypatch):
    # This map is what makes a wiki's second sweep cheap: a page whose stored
    # revision already matches never has to be fetched to find that out. It is
    # keyed the way the census stores titles -- canonically, so frwiki's
    # `Utilisateur:` and the canonical `User:` are the same page and not two.
    with_replica(monkeypatch)
    assert enumerate_with(FakeWiki()).revisions == {
        "User:Tom Smith/monobook.js": "101",
        "User:Ada/vector.css": "102",
        "User:Zoe/tools.js": "103",
    }


def test_a_page_the_replica_cannot_date_is_named_without_a_revision(monkeypatch):
    # Absent is not a claim that the page is unchanged -- it is the absence of
    # a shortcut, so the page stays in the enumeration and the sweep fetches it.
    with_replica(monkeypatch, (("javascript", "Ada/a.js", ""),))
    found = enumerate_with(FakeWiki())
    assert found.titles == ("Utilisateur:Ada/a.js",)
    assert found.revisions == {}


def test_the_search_road_offers_no_revisions_rather_than_wrong_ones(monkeypatch):
    with_replica(monkeypatch, dbname="")
    wiki = FakeWiki(titles=[("javascript", "User:A/one.js")])
    assert enumerate_with(wiki).revisions == {}


# --- falling back to the search road ---------------------------------------


def test_a_host_with_no_replica_credentials_walks_the_search_index(monkeypatch):
    with_replica(monkeypatch)
    wiki = FakeWiki(titles=[("javascript", "User:A/one.js")])
    found = enumeration.enumerate_wiki(wiki.request, FRWIKI, credentials=lambda: None, connect=None)
    assert found.source == enumeration.SOURCE_SEARCH
    assert found.titles == ("User:A/one.js",)


def test_an_unreachable_replica_falls_back_rather_than_failing_the_census(monkeypatch):
    with_replica(monkeypatch, fail=True)
    wiki = FakeWiki(titles=[("javascript", "User:A/one.js")])
    assert enumerate_with(wiki).source == enumeration.SOURCE_SEARCH_FALLBACK


def test_a_wiki_the_replica_map_has_never_heard_of_falls_back(monkeypatch):
    with_replica(monkeypatch, dbname="")
    wiki = FakeWiki(titles=[("javascript", "User:A/one.js")])
    assert enumerate_with(wiki).source == enumeration.SOURCE_SEARCH_FALLBACK


def test_a_wiki_that_will_not_name_user_space_falls_back(monkeypatch):
    # Without the namespace name there is no way to spell the titles the replica
    # returned, and a half-spelled enumeration is worse than a capped one.
    with_replica(monkeypatch)
    wiki = FakeWiki(prefix="", titles=[("javascript", "User:A/one.js")])
    assert enumerate_with(wiki).source == enumeration.SOURCE_SEARCH_FALLBACK


def test_a_replica_that_returns_nothing_falls_back_rather_than_emptying_the_wiki(monkeypatch):
    # An empty enumeration reported as complete is the one answer that would let
    # a sweep tombstone every page the wiki has.
    with_replica(monkeypatch, ())
    wiki = FakeWiki(titles=[("javascript", "User:A/one.js")])
    found = enumerate_with(wiki)
    assert found.source == enumeration.SOURCE_SEARCH_FALLBACK
    assert found.titles == ("User:A/one.js",)


def test_the_search_road_still_reports_a_capped_enumeration_as_incomplete(monkeypatch):
    with_replica(monkeypatch, fail=True)
    wiki = FakeWiki(titles=[("javascript", "User:A/one.js")], total=enumeration.census.SEARCH_OFFSET_CAP)
    found = enumerate_with(wiki)
    assert found.complete is False


def test_the_replica_road_costs_one_request_to_the_wiki(monkeypatch):
    # The point of the exercise: 34,814 pages named without 70 search requests.
    with_replica(monkeypatch)
    wiki = FakeWiki()
    enumerate_with(wiki)
    assert [params.get("meta") for params in wiki.requests] == ["siteinfo"]


# --- whether a stored census is still on the best road ---------------------


def test_a_census_from_the_index_is_superseded_once_the_replicas_are_reachable():
    # The whole point: a wiki swept before the replica road existed holds a
    # census nothing would ever revisit, because a finished sweep never runs
    # again on its own.
    assert enumeration.superseded(enumeration.SOURCE_SEARCH, credentials=lambda: USER) is True


def test_a_census_from_the_index_stands_where_there_is_no_better_road():
    assert enumeration.superseded(enumeration.SOURCE_SEARCH, credentials=lambda: None) is False


def test_a_census_from_the_replicas_is_never_superseded():
    assert enumeration.superseded(enumeration.SOURCE_REPLICA, credentials=lambda: USER) is False


def test_a_fallback_taken_with_credentials_in_hand_is_not_asked_to_try_again():
    # A replica that is present and not answering would otherwise re-sweep the
    # wiki on every run for as long as the failure lasts, which is thousands of
    # requests an hour to arrive at the same list.
    assert enumeration.superseded(enumeration.SOURCE_SEARCH_FALLBACK, credentials=lambda: USER) is False


def test_a_census_that_never_recorded_its_road_is_checked_once():
    # Rows written before the road was stored: unknown rather than exact. One
    # sweep resolves it either way, because the sweep writes down what it got.
    assert enumeration.superseded("", credentials=lambda: USER) is True
    assert enumeration.superseded("", credentials=lambda: None) is False
