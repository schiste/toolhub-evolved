"""Tests for reading a wiki's user scripts into the directory."""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_census as census, userscript_sweep as sweeper, wiki_replica  # noqa: E402
from backend.models import UserScriptCensusState, UserScriptImport, UserScriptPage  # noqa: E402

FRWIKI = "fr.wikipedia.org"


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


@pytest.fixture(autouse=True)
def _no_replica(monkeypatch, tmp_path):
    """Pin every sweep here to the search road.

    `userscript_enumeration` prefers the Wiki Replicas, and a developer machine
    that happens to carry a `replica.my.cnf` would send these sweeps down a road
    `FakeWiki` cannot answer -- so the same test would pass in CI and reach for a
    database on a laptop. Pointing the credentials at a path that does not exist
    is what CI and Toolforge-less hosts already look like, stated rather than
    assumed. The replica road has its own tests, with its own injected reader.
    """
    monkeypatch.setenv(wiki_replica.CONFIG_PATH_ENV, str(tmp_path / "absent.cnf"))


class Boom(RuntimeError):
    """A transport failure, as the client would raise it."""


class FakeWiki:
    """An Action API that answers from a dict of pages, and can be made to fail."""

    def __init__(self, pages, *, changes=None, unreadable=(), page_size=None):
        # title -> (model, body, revid, timestamp)
        self.pages = dict(pages)
        self.changes = list(changes or [])
        self.unreadable = set(unreadable)
        self.page_size = page_size or census.SEARCH_PAGE_SIZE
        self.requests = []
        self.totals = {}

    # -- dispatch -------------------------------------------------------
    def request(self, domain, method, params):
        self.requests.append((domain, method, params))
        if params.get("list") == "search":
            return self._search(params)
        if params.get("list") == "recentchanges":
            return self._changes()
        return self._content(params)

    # -- handlers -------------------------------------------------------
    def _titles_for(self, query):
        model = query.split("contentmodel:", 1)[1].split(" ", 1)[0]
        return [title for title, page in self.pages.items() if page[0] == model]

    def _search(self, params):
        titles = self._titles_for(params["srsearch"])
        total = self.totals.get(params["srsearch"], len(titles))
        offset = params.get("sroffset", 0)
        window = titles[offset : offset + self.page_size]
        return {
            "query": {
                "searchinfo": {"totalhits": total},
                "search": [{"title": title} for title in window],
            },
        }

    def _content(self, params):
        asked = params["titles"].split("|")
        if any(title in self.unreadable for title in asked):
            raise Boom(params["titles"])
        pages = []
        for title in asked:
            found = self.pages.get(title)
            if found is None:
                pages.append({"title": title, "missing": True})
                continue
            model, body, revid, stamp = found
            pages.append(
                {
                    "title": title,
                    "revisions": [
                        {
                            "revid": revid,
                            "timestamp": stamp,
                            "slots": {"main": {"contentmodel": model, "content": body}},
                        },
                    ],
                },
            )
        return {"query": {"pages": pages}}

    def _changes(self):
        return {"query": {"recentchanges": self.changes}}


def page(body, *, model="javascript", revid="1", stamp="2024-01-01T00:00:00Z"):
    return (model, body, revid, stamp)


def stored(title, wiki=FRWIKI):
    with db.session_scope() as session:
        row = (
            session.query(UserScriptPage)
            .filter(UserScriptPage.wiki == wiki, UserScriptPage.title == title)
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "role": row.role,
            "rank": row.discovery_rank,
            "revision": row.revision,
            "body": row.body,
            "owner": row.owner,
            "basename": row.basename,
            "model": row.content_model,
            "size": row.size_bytes,
            "deleted": row.deleted_at is not None,
        }


def imports_of(title, wiki=FRWIKI):
    with db.session_scope() as session:
        rows = (
            session.query(UserScriptImport)
            .filter(UserScriptImport.wiki == wiki, UserScriptImport.source_title == title)
            .all()
        )
        return sorted((row.verb, row.target_wiki, row.target_title, row.target_url) for row in rows)


def state():
    with db.session_scope() as session:
        row = session.get(UserScriptCensusState, FRWIKI)
        return {
            "sweeps": row.sweeps_completed,
            "pages": row.pages_known,
            "scripts": row.scripts_known,
            "imports": row.imports_known,
            "complete": row.enumeration_complete,
            "totals": row.enumeration_totals,
            "cursor": row.changes_cursor,
            "sweep_cursor": row.sweep_cursor,
            "status": row.status,
        }


# -- discovery ----------------------------------------------------------


def test_discovery_covers_both_content_models_in_one_pass():
    wiki = FakeWiki(
        {
            "User:A/one.js": page("var a = 1;"),
            "User:B/skin.css": page(".a{}", model="css"),
        },
    )
    found = sweeper.discover(wiki.request, FRWIKI)
    assert set(found.titles) == {"User:A/one.js", "User:B/skin.css"}
    assert found.totals == {"javascript": 1, "css": 1}
    assert found.complete is True


def test_a_model_past_the_offset_cap_makes_the_whole_discovery_incomplete():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    wiki.totals["contentmodel:javascript"] = census.SEARCH_OFFSET_CAP
    assert sweeper.discover(wiki.request, FRWIKI).complete is False


def test_discovery_order_is_the_order_the_search_index_gave():
    wiki = FakeWiki(
        {
            "User:A/one.js": page("var a = 1;"),
            "User:B/two.js": page("var b = 2;"),
            "User:C/three.js": page("var c = 3;"),
        },
        page_size=2,
    )
    found = sweeper.discover(wiki.request, FRWIKI)
    assert found.titles == ("User:A/one.js", "User:B/two.js", "User:C/three.js")


# -- reading ------------------------------------------------------------


def test_titles_are_read_in_batches_and_missing_pages_are_skipped():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    read, unreadable = sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js", "User:Gone/x.js"])
    assert [found.title for found in read] == ["User:A/one.js"]
    assert unreadable == 0


def test_a_failed_batch_is_retried_one_title_at_a_time():
    wiki = FakeWiki(
        {"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")},
        unreadable={"User:B/two.js"},
    )
    read, unreadable = sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js", "User:B/two.js"])
    # The whole batch failed on one page, and splitting rescued the other.
    assert [found.title for found in read] == ["User:A/one.js"]
    assert unreadable == 1


def test_splitting_stops_once_the_failures_look_systemic():
    titles = [f"User:U{index}/x.js" for index in range(census.CONTENT_BATCH * (sweeper.SPLIT_BUDGET + 2))]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, unreadable=set(titles))
    read, unreadable = sweeper.read_titles(wiki.request, FRWIKI, titles)
    assert read == []
    assert unreadable == len(titles)
    # Five batches were split into single reads; the rest were written off whole.
    single = [params for _d, _m, params in wiki.requests if "|" not in params["titles"]]
    assert len(single) == census.CONTENT_BATCH * sweeper.SPLIT_BUDGET


# -- storing ------------------------------------------------------------


def test_a_swept_page_is_stored_with_its_analysis_and_its_loads():
    wiki = FakeWiki(
        {
            "User:A/one.js": page(
                'importScript("User:B/two.js");\n'
                'mw.loader.load("//fr.wikipedia.org/w/index.php?title=X&action=raw");\n'
                "var a = 1;\nvar b = 2;\nvar c = 3;\nvar d = 4;\n",
            ),
        },
    )
    sweeper.sweep(wiki.request, FRWIKI)
    row = stored("User:A/one.js")
    assert row["role"] == "script"
    assert row["owner"] == "A"
    assert row["basename"] == "one.js"
    assert row["model"] == "javascript"
    assert row["size"] > 0
    assert imports_of("User:A/one.js") == [
        ("importScript", FRWIKI, "User:B/two.js", ""),
        ("mw.loader.load", FRWIKI, "X", "//fr.wikipedia.org/w/index.php?title=X&action=raw"),
    ]


def test_the_owner_is_stored_from_a_namespace_no_alias_list_knows():
    # `canonical_title` folds the namespace aliases it knows -- English and the
    # two French spellings -- onto `User:`, and every other wiki keeps its own
    # prefix. Reading the owner by position rather than by name is what makes
    # this work on a wiki nobody has enumerated the aliases for.
    wiki = FakeWiki({"Benutzer:EDUCA33E/LiveRC.js": page("var a = 1;\nvar b = 2;\nvar c = 3;\n")})
    sweeper.sweep(wiki.request, "de.wikipedia.org")
    row = stored("Benutzer:EDUCA33E/LiveRC.js", wiki="de.wikipedia.org")
    assert (row["owner"], row["basename"]) == ("EDUCA33E", "LiveRC.js")


def test_a_french_title_is_folded_onto_the_canonical_namespace_before_storage():
    # The alias list does cover frwiki, so its rows are stored as `User:` and
    # the owner comes out the same way. Both spellings must land on one page.
    wiki = FakeWiki({"Utilisateur:EDUCA33E/LiveRC.js": page("var a = 1;\nvar b = 2;\nvar c = 3;\n")})
    sweeper.sweep(wiki.request, FRWIKI)
    row = stored("User:EDUCA33E/LiveRC.js")
    assert (row["owner"], row["basename"]) == ("EDUCA33E", "LiveRC.js")


def test_a_page_stores_the_content_model_the_wiki_reports_not_its_suffix():
    wiki = FakeWiki({"User:Penquista/monobook.css": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    assert stored("User:Penquista/monobook.css")["model"] == "javascript"


def test_a_body_larger_than_the_cap_is_truncated_but_still_measured_whole():
    body = "// " + ("x" * (sweeper.MAX_STORED_BODY * 2))
    wiki = FakeWiki({"User:A/one.js": page(body)})
    sweeper.sweep(wiki.request, FRWIKI)
    row = stored("User:A/one.js")
    assert len(row["body"]) == sweeper.MAX_STORED_BODY
    assert row["size"] == len(body.encode("utf-8"))


def test_the_same_load_written_twice_is_stored_once():
    wiki = FakeWiki({"User:A/one.js": page('importScript("User:B/two.js");\nimportScript("User:B/two.js");')})
    sweeper.sweep(wiki.request, FRWIKI)
    assert imports_of("User:A/one.js") == [("importScript", FRWIKI, "User:B/two.js", "")]


def test_a_load_removed_from_a_page_stops_counting_as_demand():
    wiki = FakeWiki({"User:A/one.js": page('importScript("User:B/two.js");')})
    sweeper.sweep(wiki.request, FRWIKI)
    assert imports_of("User:A/one.js")
    wiki.pages["User:A/one.js"] = page("var a = 1;", revid="2")
    sweeper.sweep(wiki.request, FRWIKI)
    assert imports_of("User:A/one.js") == []


# -- skipping -----------------------------------------------------------


def test_a_page_whose_revision_has_not_moved_is_not_rewritten():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    first = sweeper.sweep(wiki.request, FRWIKI)
    second = sweeper.sweep(wiki.request, FRWIKI)
    assert first["written"] == 1
    assert second == {**second, "written": 0, "skipped": 1}


def test_a_page_whose_revision_moved_is_rewritten():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.pages["User:A/one.js"] = page("var a = 1;\nimportScript('User:B/two.js');", revid="2")
    second = sweeper.sweep(wiki.request, FRWIKI)
    assert second["written"] == 1
    assert imports_of("User:A/one.js")


def test_an_unchanged_page_that_moved_in_creation_order_is_rewritten():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    assert stored("User:A/one.js")["rank"] == 0
    wiki.pages = {"User:Z/zero.js": page("var z = 0;"), **wiki.pages}
    second = sweeper.sweep(wiki.request, FRWIKI)
    assert second["written"] == 2
    assert stored("User:A/one.js")["rank"] == 1


# -- creation order -----------------------------------------------------


def test_rank_follows_the_search_index_order_not_the_alphabet():
    wiki = FakeWiki(
        {
            "User:Z/late.js": page("var z = 1;"),
            "User:A/early.js": page("var a = 1;"),
        },
    )
    sweeper.sweep(wiki.request, FRWIKI)
    assert stored("User:Z/late.js")["rank"] == 0
    assert stored("User:A/early.js")["rank"] == 1


def test_a_page_first_seen_in_recent_changes_sorts_after_everything_swept():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.pages["User:C/new.js"] = page("var c = 3;")
    wiki.changes = [{"ns": 2, "title": "User:C/new.js", "timestamp": "2024-02-01T00:00:00Z"}]
    sweeper.watch(wiki.request, FRWIKI)
    assert stored("User:C/new.js")["rank"] == 2


def test_a_watch_leaves_the_creation_order_of_a_page_it_re_reads_alone():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.pages["User:A/one.js"] = page("var a = 2;", revid="9")
    wiki.changes = [{"ns": 2, "title": "User:A/one.js", "timestamp": "2024-02-01T00:00:00Z"}]
    sweeper.watch(wiki.request, FRWIKI)
    assert stored("User:A/one.js")["rank"] == 0
    assert stored("User:A/one.js")["revision"] == "9"


# -- disappearance ------------------------------------------------------


def test_a_page_a_complete_sweep_no_longer_lists_is_tombstoned():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI)
    del wiki.pages["User:B/two.js"]
    summary = sweeper.sweep(wiki.request, FRWIKI)
    assert summary["removed"] == 1
    assert stored("User:B/two.js")["deleted"] is True
    assert stored("User:A/one.js")["deleted"] is False


def test_a_tombstoned_page_that_comes_back_is_live_again():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    saved = wiki.pages.pop("User:A/one.js")
    sweeper.sweep(wiki.request, FRWIKI)
    assert stored("User:A/one.js")["deleted"] is True
    wiki.pages["User:A/one.js"] = saved
    sweeper.sweep(wiki.request, FRWIKI)
    assert stored("User:A/one.js")["deleted"] is False


def test_a_limited_sweep_never_declares_the_pages_it_skipped_gone():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI)
    summary = sweeper.sweep(wiki.request, FRWIKI, limit=1)
    assert summary["removed"] == 0
    assert stored("User:B/two.js")["deleted"] is False


def test_an_incomplete_enumeration_never_declares_anything_gone():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.totals["contentmodel:javascript"] = census.SEARCH_OFFSET_CAP
    summary = sweeper.sweep(wiki.request, FRWIKI)
    assert summary["removed"] == 0
    assert summary["complete"] is False


# -- covering a wiki over several runs -----------------------------------

# Three pages, one per run at limit=1, so the cursor has to carry twice.
THREE = {
    "User:A/one.js": page("var a = 1;"),
    "User:B/two.js": page("var b = 2;"),
    "User:C/three.js": page("var c = 3;"),
}


def test_a_bounded_sweep_reads_its_slice_and_records_where_it_stopped():
    summary = sweeper.sweep(FakeWiki(THREE).request, FRWIKI, limit=1)
    assert summary["asked"] == 1
    assert summary["enumerated"] == 3
    assert summary["sweep_cursor"] == 1


def test_the_next_bounded_sweep_continues_instead_of_re_reading_the_first_slice():
    wiki = FakeWiki(THREE)
    sweeper.sweep(wiki.request, FRWIKI, limit=1)
    sweeper.sweep(wiki.request, FRWIKI, limit=1)
    assert stored("User:B/two.js") is not None
    assert state()["sweep_cursor"] == 2


def test_successive_bounded_sweeps_cover_a_wiki_a_single_run_could_not():
    wiki = FakeWiki(THREE)
    for _run in range(3):
        sweeper.sweep(wiki.request, FRWIKI, limit=1)
    assert all(stored(title) is not None for title in THREE)


def test_a_page_read_in_a_later_slice_keeps_its_place_in_creation_order():
    # The rank is a position in the whole enumeration, not in the batch. A slice
    # numbered from zero would tell the directory the third page ever created
    # was the first, and the collapse breaks its ties on exactly that.
    wiki = FakeWiki(THREE)
    for _run in range(3):
        sweeper.sweep(wiki.request, FRWIKI, limit=1)
    assert [stored(title)["rank"] for title in THREE] == [0, 1, 2]


def test_a_sweep_still_running_is_not_a_completed_sweep():
    sweeper.sweep(FakeWiki(THREE).request, FRWIKI, limit=1)
    assert state()["sweeps"] == 0


def test_the_run_that_reaches_the_end_completes_the_sweep_and_clears_the_cursor():
    wiki = FakeWiki(THREE)
    for _run in range(3):
        sweeper.sweep(wiki.request, FRWIKI, limit=1)
    assert (state()["sweeps"], state()["sweep_cursor"], state()["complete"]) == (1, 0, True)


def test_only_the_run_that_reaches_the_end_may_declare_a_page_gone():
    wiki = FakeWiki(THREE)
    for _run in range(3):
        sweeper.sweep(wiki.request, FRWIKI, limit=1)
    del wiki.pages["User:A/one.js"]
    removed = [sweeper.sweep(wiki.request, FRWIKI, limit=1)["removed"] for _run in range(2)]
    assert removed == [0, 1]
    assert stored("User:A/one.js")["deleted"] is True


def test_a_cursor_into_an_enumeration_that_cannot_be_trusted_is_dropped():
    # A capped search returns a prefix whose length depends on what the index
    # will serve, so position 1 in this run's list need not be position 1 in the
    # next one. Restarting costs a pass; carrying on could skip pages silently.
    wiki = FakeWiki(THREE)
    sweeper.sweep(wiki.request, FRWIKI, limit=1)
    wiki.totals["contentmodel:javascript"] = census.SEARCH_OFFSET_CAP
    assert sweeper.sweep(wiki.request, FRWIKI, limit=1)["asked"] == 1
    assert stored("User:A/one.js")["rank"] == 0


def test_a_cursor_past_the_end_of_a_shrunken_wiki_restarts_it():
    wiki = FakeWiki(THREE)
    sweeper.sweep(wiki.request, FRWIKI, limit=2)
    wiki.pages = {"User:A/one.js": page("var a = 1;")}
    assert sweeper.sweep(wiki.request, FRWIKI)["sweep_cursor"] == 0
    assert state()["sweeps"] == 1


def test_an_unbounded_sweep_finishes_in_one_run_as_it_always_did():
    summary = sweeper.sweep(FakeWiki(THREE).request, FRWIKI)
    assert (summary["asked"], summary["sweep_cursor"]) == (3, 0)
    assert state()["sweeps"] == 1


# -- state --------------------------------------------------------------


def test_a_sweep_records_what_it_learned_about_the_wiki():
    wiki = FakeWiki(
        {
            "User:A/one.js": page('importScript("User:B/two.js");\nvar a = 1;\nvar b = 2;\nvar c = 3;\nvar d = 4;\n'),
            "User:B/two.js": page("// nothing yet"),
            "User:C/skin.css": page(".a{}", model="css"),
        },
    )
    sweeper.sweep(wiki.request, FRWIKI)
    assert state() == {
        "sweeps": 1,
        "pages": 3,
        "scripts": 1,
        "imports": 1,
        "complete": True,
        "totals": {"javascript": 2, "css": 1},
        "cursor": "",
        "sweep_cursor": 0,
        "status": "idle",
    }


def test_a_limited_sweep_does_not_claim_the_enumeration_was_complete():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI, limit=1)
    assert state()["complete"] is False


def test_a_sweep_of_a_wiki_with_no_pages_still_leaves_a_state_row():
    wiki = FakeWiki({})
    summary = sweeper.sweep(wiki.request, FRWIKI)
    assert summary["asked"] == 0
    assert state()["sweeps"] == 1


# -- watching -----------------------------------------------------------


def test_a_watch_reads_only_what_changed():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.pages["User:B/two.js"] = page("var b = 3;", revid="7")
    wiki.changes = [{"ns": 2, "title": "User:B/two.js", "timestamp": "2024-03-01T00:00:00Z"}]
    summary = sweeper.watch(wiki.request, FRWIKI)
    assert summary["asked"] == 1
    assert summary["written"] == 1
    assert summary["cursor"] == "2024-03-01T00:00:00Z"


def test_a_watch_with_nothing_to_read_asks_for_no_content():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    before = len(wiki.requests)
    summary = sweeper.watch(wiki.request, FRWIKI)
    assert summary["asked"] == 0
    assert len(wiki.requests) == before + 1


def test_a_quiet_window_leaves_the_cursor_where_it_was():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.changes = [{"ns": 2, "title": "User:A/one.js", "timestamp": "2024-03-01T00:00:00Z"}]
    sweeper.watch(wiki.request, FRWIKI)
    wiki.changes = []
    assert sweeper.watch(wiki.request, FRWIKI)["cursor"] == "2024-03-01T00:00:00Z"


def test_the_cursor_is_the_newest_timestamp_the_window_held():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.changes = [
        {"ns": 2, "title": "User:A/one.js", "timestamp": "2024-03-01T00:00:00Z"},
        {"ns": 2, "title": "User:A/one.js", "timestamp": "2024-03-05T00:00:00Z"},
    ]
    assert sweeper.watch(wiki.request, FRWIKI)["cursor"] == "2024-03-05T00:00:00Z"


@pytest.mark.parametrize(
    "payload",
    [
        "not a dict",
        {},
        {"query": {}},
        {"query": {"recentchanges": "not a list"}},
        {"query": {"recentchanges": [{"title": "x"}, "junk"]}},
    ],
)
def test_a_feed_with_no_usable_timestamp_keeps_the_old_cursor(payload):
    assert sweeper.latest_timestamp(payload, "2024-01-01T00:00:00Z") == "2024-01-01T00:00:00Z"


# -- choosing between the two -------------------------------------------


def test_a_wiki_that_has_never_been_swept_is_swept_whatever_was_asked_for():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    assert sweeper.run(wiki.request, FRWIKI)["mode"] == "sweep"


def test_a_swept_wiki_is_watched_by_default():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.run(wiki.request, FRWIKI)
    assert sweeper.run(wiki.request, FRWIKI)["mode"] == "watch"


def test_a_wiki_part_way_through_a_sweep_keeps_sweeping_rather_than_watching():
    # A watch reports the handful of pages that changed this hour. Falling
    # through to one with two thirds of the wiki still unread would leave the
    # rest unread forever, and the state row would say the wiki was covered.
    wiki = FakeWiki(THREE)
    sweeper.run(wiki.request, FRWIKI, limit=1)
    assert sweeper.run(wiki.request, FRWIKI, limit=1)["mode"] == "sweep"


def test_a_wiki_watches_again_once_its_sweep_has_reached_the_end():
    wiki = FakeWiki(THREE)
    for _run in range(3):
        sweeper.run(wiki.request, FRWIKI, limit=1)
    assert sweeper.run(wiki.request, FRWIKI, limit=1)["mode"] == "watch"


def test_a_full_run_sweeps_a_wiki_that_was_already_swept():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.run(wiki.request, FRWIKI)
    assert sweeper.run(wiki.request, FRWIKI, full=True)["mode"] == "sweep"


# -- the job entrypoint -------------------------------------------------

import userscript_sweep as job  # noqa: E402

#: What `userscript_sweep.run` hands back for a sweep. Spelled out here because
#: the job's log line reads every one of these keys, so a stub that answered
#: with fewer would pass while the job itself raised in production.
SWEPT = {
    "mode": "sweep",
    "asked": 0,
    "fetched": 0,
    "written": 0,
    "skipped": 0,
    "unreadable": 0,
    "source": "replica",
    "enumerated": 0,
    "sweep_cursor": 0,
    "complete": True,
}


@pytest.fixture
def _job_env(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.setattr(job, "WikimediaClient", lambda: FakeWiki({"User:A/one.js": page("var a = 1;")}))


def test_the_job_sweeps_the_configured_wikis(monkeypatch, capsys, _job_env):
    seen = []
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org, en.wikipedia.org ,")
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **kwargs: seen.append((wiki, kwargs))
        or dict(SWEPT, wiki=wiki, asked=1, fetched=1, written=1),
    )
    assert job.main() == 0
    assert [wiki for wiki, _kwargs in seen] == ["fr.wikipedia.org", "en.wikipedia.org"]
    assert seen[0][1] == {"full": False, "limit": 0, "watch_limit": sweeper.WATCH_LIMIT}
    out = capsys.readouterr().out
    assert "userscript-census: wiki=fr.wikipedia.org mode=sweep" in out
    assert "unreadable=0" in out


def test_the_job_defaults_to_the_pilot_wikis_and_really_writes_rows(monkeypatch, capsys, _job_env):
    # frwiki is the corpus under study; meta is where global.js lives, and its
    # cross-wiki loads are the whole argument for a script becoming a gadget.
    monkeypatch.delenv("USERSCRIPT_WIKIS", raising=False)
    assert job.main() == 0
    out = capsys.readouterr().out
    assert "wiki=fr.wikipedia.org mode=sweep" in out
    assert "wiki=meta.wikimedia.org mode=sweep" in out


def test_a_full_run_is_asked_for_through_the_environment(monkeypatch, _job_env):
    asked = []
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")  # one wiki: this is about the options, not the list
    monkeypatch.setenv("USERSCRIPT_SWEEP", "YES")
    monkeypatch.setenv("USERSCRIPT_LIMIT", "40")
    monkeypatch.setenv("USERSCRIPT_WATCH_LIMIT", "80")
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **kwargs: asked.append(kwargs)
        or dict(SWEPT, wiki=wiki),
    )
    assert job.main() == 0
    assert asked == [{"full": True, "limit": 40, "watch_limit": 80}]


@pytest.mark.parametrize(("raw", "expected"), [("", 500), ("nonsense", 500), ("-5", 500), ("0", 500), ("12", 12)])
def test_an_unusable_watch_limit_falls_back_to_the_default(monkeypatch, raw, expected, _job_env):
    asked = []
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")  # one wiki: this is about the options, not the list
    monkeypatch.setenv("USERSCRIPT_WATCH_LIMIT", raw)
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **kwargs: asked.append(kwargs["watch_limit"])
        or {"wiki": wiki, "mode": "watch", "asked": 0, "fetched": 0, "written": 0, "skipped": 0, "unreadable": 0},
    )
    assert job.main() == 0
    assert asked == [expected]
