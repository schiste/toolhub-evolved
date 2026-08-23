"""Tests for reading a wiki's user scripts into the directory."""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_census as census, userscript_sweep as sweeper  # noqa: E402
from backend import userscripts, wiki_replica  # noqa: E402
from backend.models import UserScriptCensusState, UserScriptImport, UserScriptPage  # noqa: E402

FRWIKI = "fr.wikipedia.org"
ENWIKI = "en.wikipedia.org"


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


class Lagging(RuntimeError):
    """A maxlag refusal, as `WikimediaClient` normalizes it: an error with a code."""

    code = census.MAXLAG_ERROR


class FakeWiki:
    """An Action API that answers from a dict of pages, and can be made to fail."""

    def __init__(
        self,
        pages,
        *,
        changes=None,
        unreadable=(),
        page_size=None,
        lagged_after=None,
        namespace_name="User",
        namespace_aliases=(),
    ):
        # title -> (model, body, revid, timestamp)
        self.pages = dict(pages)
        self.changes = list(changes or [])
        self.unreadable = set(unreadable)
        self.page_size = page_size or census.SEARCH_PAGE_SIZE
        #: Content requests to answer before the wiki starts refusing for lag,
        #: so a test can put the refusal in the middle of a run rather than at
        #: its start -- which is where it does the damage.
        self.lagged_after = lagged_after
        #: What this wiki calls namespace 2, and what else it answers to for it.
        #: Defaulted to a plain English wiki so that a test which is not about
        #: namespaces reads like one -- but answered rather than omitted,
        #: because a fake that cannot answer siteinfo would make every sweep
        #: here silently fall back to the built-in spellings.
        self.namespace_name = namespace_name
        self.namespace_aliases = tuple(namespace_aliases)
        self.content_requests = 0
        self.requests = []
        self.totals = {}

    # -- dispatch -------------------------------------------------------
    def request(self, domain, method, params):
        self.requests.append((domain, method, params))
        if params.get("meta") == "siteinfo":
            return self._siteinfo()
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
        self.content_requests += 1
        if self.lagged_after is not None and self.content_requests > self.lagged_after:
            raise Lagging("Waiting for a database server: 9 seconds lagged.")
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

    def _siteinfo(self):
        # Shaped like the real answer: `canonical` is `User` on every wiki,
        # `name` is the localized one, and aliases are a separate list keyed by
        # namespace id -- which is why the fold cannot be derived from `name`
        # alone.
        return {
            "query": {
                "namespaces": {"2": {"id": 2, "canonical": "User", "name": self.namespace_name}},
                "namespacealiases": [{"id": 2, "alias": alias} for alias in self.namespace_aliases],
            },
        }


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


def resolved_targets(title, wiki=FRWIKI):
    """Which page each of a source's loads points at, named rather than numbered.

    Reading the edge back as `(wiki, title)` rather than as an id is deliberate:
    a test that asserted on the number would pass just as happily if the resolver
    pointed every load at the same wrong row.
    """
    with db.session_scope() as session:
        pages = {row.id: (row.wiki, row.title) for row in session.query(UserScriptPage).all()}
        rows = (
            session.query(UserScriptImport)
            .filter(UserScriptImport.wiki == wiki, UserScriptImport.source_title == title)
            .all()
        )
        return {row.target_title: pages.get(row.target_page_id) for row in rows}


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
    read, unreadable, _lagged = sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js", "User:Gone/x.js"])
    assert [found.title for found in read] == ["User:A/one.js"]
    assert unreadable == 0


def test_a_failed_batch_is_retried_one_title_at_a_time():
    wiki = FakeWiki(
        {"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")},
        unreadable={"User:B/two.js"},
    )
    read, unreadable, _lagged = sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js", "User:B/two.js"])
    # The whole batch failed on one page, and splitting rescued the other.
    assert [found.title for found in read] == ["User:A/one.js"]
    assert unreadable == 1


def test_a_fat_batch_is_halved_rather_than_taken_apart_title_by_title():
    # This is what lets `CONTENT_BATCH` be set by what the API will answer
    # rather than by what a bad batch costs to recover from: one page too big
    # for the response cap costs a handful of extra requests, not one per title.
    titles = [f"User:U{index}/x.js" for index in range(8)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, unreadable={"User:U5/x.js"})
    read, unreadable, _lagged = sweeper.read_titles(wiki.request, FRWIKI, titles)
    assert [found.title for found in read] == [title for title in titles if title != "User:U5/x.js"]
    assert unreadable == 1
    asked = [params["titles"].split("|") for _d, _m, params in wiki.requests]
    # The halves are visible in the sizes asked for, and only the pair either
    # side of the unreadable page was ever read alone: seven requests where
    # falling straight to single titles would have cost nine.
    assert sorted(len(batch) for batch in asked) == [1, 1, 2, 2, 4, 4, 8]


def test_every_content_request_asks_the_wiki_to_refuse_it_when_replicas_are_behind():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js"])
    assert wiki.requests[0][2]["maxlag"] == census.MAXLAG_SECONDS


def test_a_wiki_that_says_it_is_behind_is_not_asked_the_same_batch_in_halves():
    # The whole point of telling a lag refusal apart from an oversized batch.
    # Both fail a batch identically, and the split would answer a wiki asking
    # for less traffic with about six times as many requests.
    titles = [f"User:U{index}/x.js" for index in range(census.CONTENT_BATCH * 2)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, lagged_after=1)
    read, unreadable, lagged = sweeper.read_titles(wiki.request, FRWIKI, titles)
    assert lagged is True
    # One batch answered, one refused, and nothing after it: no halving.
    assert wiki.content_requests == 2
    assert len(read) == census.CONTENT_BATCH
    # The titles behind the refusal were never asked for, so they are not
    # unreadable -- calling them that would record them as covered and looked at.
    assert unreadable == 0


def test_a_wiki_s_own_namespace_name_is_read_and_folds_its_titles():
    # Until the sweep asked, the fold knew `User`, `Utilisateur` and
    # `Utilisatrice` and nothing else, so every dewiki page was stored under a
    # title no page answers to and every load edge into it resolved to nothing.
    dewiki = "de.wikipedia.org"
    wiki = FakeWiki(
        {
            "Benutzer:PerfektesChaos/js/lint.js": page("importScript('Benutzer:PerfektesChaos/js/core.js');"),
            "Benutzer:PerfektesChaos/js/core.js": page("var core = 1;"),
        },
        namespace_name="Benutzer",
        namespace_aliases=("Benutzerin",),
    )
    sweeper.ingest(wiki.request, dewiki, list(wiki.pages), ranked=True)
    assert stored("User:PerfektesChaos/js/lint.js", wiki=dewiki) is not None
    assert stored("Benutzer:PerfektesChaos/js/lint.js", wiki=dewiki) is None
    # And the load edge lands on the row rather than dangling, which is the
    # whole point of folding the title in the first place.
    targets = resolved_targets("User:PerfektesChaos/js/lint.js", wiki=dewiki)
    assert targets == {"User:PerfektesChaos/js/core.js": (dewiki, "User:PerfektesChaos/js/core.js")}


def test_one_sweep_asks_a_wiki_for_its_namespace_names_once():
    titles = [f"Benutzer:U{index}/x.js" for index in range(census.CONTENT_BATCH + 5)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, namespace_name="Benutzer")
    sweeper.ingest(wiki.request, "de.wikipedia.org", titles, ranked=True)
    siteinfo = [asked for asked in wiki.requests if asked[2].get("meta") == "siteinfo"]
    # Once, not once per page and not once per resolver: a sweep that paid a
    # request per load edge would cost more in namespace lookups than in content.
    assert len(siteinfo) == 1


def test_a_wiki_that_will_not_say_what_it_calls_its_namespace_is_swept_anyway():
    # The fold falls back to the built-ins, which is exactly the behavior that
    # existed before any of this. An unreadable siteinfo must cost coverage,
    # not the run.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    wiki._siteinfo = lambda: (_ for _ in ()).throw(Boom("siteinfo"))
    summary = sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js"], ranked=True)
    assert summary["written"] == 1
    assert stored("User:A/one.js") is not None


def test_pages_read_before_the_refusal_are_still_written():
    titles = [f"User:U{index}/x.js" for index in range(census.CONTENT_BATCH * 2)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, lagged_after=1)
    summary = sweeper.ingest(wiki.request, FRWIKI, titles, ranked=True)
    assert summary["written"] == census.CONTENT_BATCH
    assert summary["lagged"] == 1


def test_a_sweep_cut_short_by_lag_leaves_its_cursor_where_it_was():
    # The cursor is the only record that the window was not covered. Advancing
    # it over pages nobody asked for would drop them until the next full sweep.
    titles = [f"User:U{index:03d}/x.js" for index in range(census.CONTENT_BATCH * 2)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, lagged_after=1)
    summary = sweeper.sweep(wiki.request, FRWIKI, limit=len(titles))
    assert summary["lagged"] == 1
    assert summary["sweep_cursor"] == 0
    with db.session_scope() as session:
        state = session.query(UserScriptCensusState).filter_by(wiki=FRWIKI).one()
    assert state.sweep_cursor == 0
    # And it is not a completed sweep, so nothing was tombstoned as gone.
    assert state.sweeps_completed == 0
    assert state.enumeration_complete is False


def test_a_watch_cut_short_by_lag_leaves_its_cursor_where_it_was():
    # A watch has no second pass: an advanced cursor loses those edits for good.
    wiki = FakeWiki(
        {"User:A/one.js": page("var a = 1;")},
        changes=[{"title": "User:A/one.js", "ns": 2, "timestamp": "2026-01-02T00:00:00Z"}],
        lagged_after=0,
    )
    summary = sweeper.watch(wiki.request, FRWIKI)
    assert summary["lagged"] == 1
    assert summary["cursor"] == ""


def test_splitting_stops_once_the_failures_look_systemic():
    titles = [f"User:U{index}/x.js" for index in range(census.CONTENT_BATCH * (sweeper.SPLIT_BUDGET + 2))]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, unreadable=set(titles))
    read, unreadable, _lagged = sweeper.read_titles(wiki.request, FRWIKI, titles)
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


# -- resolving loads to pages -------------------------------------------


def test_a_load_points_at_the_page_it_names_when_both_arrive_in_one_run():
    wiki = FakeWiki(
        {
            "User:A/one.js": page('importScript("User:B/two.js");'),
            "User:B/two.js": page("var b = 2;"),
        },
    )
    summary = sweeper.sweep(wiki.request, FRWIKI)
    assert resolved_targets("User:A/one.js") == {"User:B/two.js": (FRWIKI, "User:B/two.js")}
    assert summary["resolved"] == 1


def test_a_page_written_now_finds_the_page_it_loads_from_an_earlier_run():
    # The loader arrives second. Resolution has to look outward, from this run's
    # pages to whatever the corpus already holds.
    wiki = FakeWiki({"User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.pages["User:A/one.js"] = page('importScript("User:B/two.js");')
    sweeper.sweep(wiki.request, FRWIKI)
    assert resolved_targets("User:A/one.js") == {"User:B/two.js": (FRWIKI, "User:B/two.js")}


def test_a_page_written_now_is_found_by_the_loads_that_were_waiting_for_it():
    # The loader arrives first, and its load is unresolvable at the time. Nothing
    # rewrites that page later, so only a resolver that also looks inward -- from
    # this run's pages back to whoever names them -- ever closes this edge.
    wiki = FakeWiki({"User:A/one.js": page('importScript("User:B/two.js");')})
    sweeper.sweep(wiki.request, FRWIKI)
    assert resolved_targets("User:A/one.js") == {"User:B/two.js": None}
    wiki.pages["User:B/two.js"] = page("var b = 2;")
    second = sweeper.sweep(wiki.request, FRWIKI)
    assert second["skipped"] == 1
    assert resolved_targets("User:A/one.js") == {"User:B/two.js": (FRWIKI, "User:B/two.js")}


def test_a_load_naming_a_page_the_census_does_not_hold_stays_unresolved():
    # Null is the honest answer, not a gap to be filled. A user script may load a
    # page that was deleted, renamed, or never existed, and inventing a row for
    # it would turn a broken load into a working one.
    wiki = FakeWiki({"User:A/one.js": page('importScript("User:B/gone.js");')})
    sweeper.sweep(wiki.request, FRWIKI)
    assert resolved_targets("User:A/one.js") == {"User:B/gone.js": None}


def test_a_load_of_another_wiki_resolves_once_that_wiki_has_been_swept():
    # Cross-wiki loads are how a script becomes shared infrastructure, and the
    # wikis are swept independently, so the edge is nearly always closed by the
    # run that reads the *target* -- long after the run that read the loader.
    loader = 'mw.loader.load("//en.wikipedia.org/w/index.php?title=User:C/three.js&action=raw");'
    fr = FakeWiki({"User:A/one.js": page(loader)})
    sweeper.sweep(fr.request, FRWIKI)
    assert resolved_targets("User:A/one.js") == {"User:C/three.js": None}
    en = FakeWiki({"User:C/three.js": page("var c = 3;")})
    sweeper.sweep(en.request, ENWIKI)
    assert resolved_targets("User:A/one.js") == {"User:C/three.js": (ENWIKI, "User:C/three.js")}


def test_a_rewritten_page_does_not_lose_the_edges_it_still_has():
    # Storing a page replaces its loads wholesale, which drops every resolution
    # it had. The run that replaced them has to put them back, or an edited page
    # would silently disconnect from the graph.
    wiki = FakeWiki(
        {
            "User:A/one.js": page('importScript("User:B/two.js");'),
            "User:B/two.js": page("var b = 2;"),
        },
    )
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.pages["User:A/one.js"] = page('importScript("User:B/two.js");\nvar a = 1;', revid="2")
    sweeper.sweep(wiki.request, FRWIKI)
    assert resolved_targets("User:A/one.js") == {"User:B/two.js": (FRWIKI, "User:B/two.js")}


def test_a_watch_resolves_the_page_it_read_just_as_a_sweep_does():
    wiki = FakeWiki({"User:B/two.js": page("var b = 2;")})
    sweeper.sweep(wiki.request, FRWIKI)
    wiki.pages["User:A/one.js"] = page('importScript("User:B/two.js");')
    wiki.changes = [{"ns": 2, "title": "User:A/one.js", "timestamp": "2024-02-01T00:00:00Z"}]
    sweeper.watch(wiki.request, FRWIKI)
    assert resolved_targets("User:A/one.js") == {"User:B/two.js": (FRWIKI, "User:B/two.js")}


# -- skipping -----------------------------------------------------------


def test_a_page_the_enumeration_says_has_not_moved_is_never_asked_for():
    # The point of carrying `page_latest` out of the replica. Fetching is the
    # entire cost of a sweep, so a page settled before the request is a request
    # that never happens -- which is what makes a wiki's second sweep cheap.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;", revid="7")})
    sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js"], ranked=True)
    before = len(wiki.requests)
    summary = sweeper.ingest(
        wiki.request,
        FRWIKI,
        ["User:A/one.js"],
        ranked=True,
        revisions={"User:A/one.js": "7"},
    )
    assert (summary["skipped"], summary["fetched"], summary["written"]) == (1, 0, 0)
    assert len(wiki.requests) == before


def test_a_page_the_enumeration_says_moved_is_fetched_and_rewritten():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;", revid="7")})
    sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js"], ranked=True)
    wiki.pages["User:A/one.js"] = page("var a = 2;", revid="8")
    summary = sweeper.ingest(
        wiki.request,
        FRWIKI,
        ["User:A/one.js"],
        ranked=True,
        revisions={"User:A/one.js": "8"},
    )
    assert (summary["skipped"], summary["fetched"], summary["written"]) == (0, 1, 1)
    assert stored("User:A/one.js")["body"] == "var a = 2;"


def test_a_page_the_enumeration_cannot_date_is_fetched_rather_than_assumed_unchanged():
    # A missing revision is the absence of a shortcut, not evidence of anything.
    # Treating it as unchanged would let one gap in the replica's answer freeze
    # a page in the directory at whatever it last happened to say.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;", revid="7")})
    sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js"], ranked=True)
    summary = sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js"], ranked=True, revisions={})
    assert summary["fetched"] == 1


def test_an_unmoved_page_that_shifted_in_creation_order_is_still_fetched():
    # Rank is stored on the page row, so a page whose body never changed but
    # whose position did has to be written -- and the pre-fetch skip must not
    # settle it on the revision alone.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;", revid="7")})
    sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js"], ranked=True)
    summary = sweeper.ingest(
        wiki.request,
        FRWIKI,
        ["User:A/one.js"],
        ranked=True,
        rank_offset=5,
        revisions={"User:A/one.js": "7"},
    )
    assert (summary["fetched"], summary["written"]) == (1, 1)
    assert stored("User:A/one.js")["rank"] == 5


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


# -- and re-choosing it when the road moves under the census ------------


def _looks_like_toolforge(monkeypatch, tmp_path):
    """Give this host replica credentials, and no replica to use them on.

    Both halves matter. The credentials are what makes the exact road *look*
    available, which is the condition a stored census is measured against; the
    reader that raises is what every host without a live replica behind those
    credentials actually does, and what the fallback exists to survive. Left to
    connect for real this would sit on a DNS timeout instead.
    """
    path = tmp_path / "replica.my.cnf"
    path.write_text("[client]\nuser='s55555'\npassword='sekrit'\n", encoding="utf-8")
    monkeypatch.setenv(wiki_replica.CONFIG_PATH_ENV, str(path))

    def unreachable(*_args, **_kwargs):
        raise Boom("no replica behind these credentials")

    monkeypatch.setattr(wiki_replica, "dbnames_for", unreachable)


def _recorded(wiki=FRWIKI):
    with db.session_scope() as session:
        state = session.get(UserScriptCensusState, wiki)
        return (state.enumeration_source, state.sweeps_completed)


def test_a_sweep_writes_down_which_road_named_the_pages():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.run(wiki.request, FRWIKI)
    assert _recorded() == ("search", 1)


def test_a_census_built_on_the_capped_road_is_swept_again_once_the_exact_one_is_reachable(
    monkeypatch, tmp_path
):
    # The defect this exists for. frwiki finished a sweep from the search index
    # the day before the replica road landed, and a finished sweep never runs
    # again -- so it watched for changes over a census 920 pages short of the
    # wiki, and nothing in the state row disagreed.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.run(wiki.request, FRWIKI)
    assert sweeper.run(wiki.request, FRWIKI)["mode"] == "watch"
    _looks_like_toolforge(monkeypatch, tmp_path)
    assert sweeper.run(wiki.request, FRWIKI)["mode"] == "sweep"


def test_a_census_that_never_recorded_its_road_is_swept_once_and_then_knows(monkeypatch, tmp_path):
    # What every row in the table looked like before the column existed. Blank
    # is unknown, not exact, and one sweep is what turns it into either.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    sweeper.run(wiki.request, FRWIKI)
    with db.session_scope() as session:
        session.get(UserScriptCensusState, FRWIKI).enumeration_source = ""
    _looks_like_toolforge(monkeypatch, tmp_path)
    assert sweeper.run(wiki.request, FRWIKI)["mode"] == "sweep"
    assert _recorded()[0] == "search-fallback"


def test_a_replica_that_is_present_and_failing_does_not_re_sweep_the_wiki_every_run(
    monkeypatch, tmp_path
):
    # The loop this could have been. Asking "is a better road available" of the
    # credentials alone would sweep the wiki on every run for as long as the
    # replica stayed down -- thousands of requests an hour to arrive at exactly
    # the list already stored. What the census records is the road it got, not
    # the road it hoped for.
    _looks_like_toolforge(monkeypatch, tmp_path)
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    assert sweeper.run(wiki.request, FRWIKI)["mode"] == "sweep"
    assert _recorded()[0] == "search-fallback"
    assert sweeper.run(wiki.request, FRWIKI)["mode"] == "watch"


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
    "lagged": 0,
    "source": "replica",
    "enumerated": 0,
    "sweep_cursor": 0,
    "complete": True,
}

#: The same for a watch, whose log line reads a cursor a sweep does not have.
WATCHED = {
    "mode": "watch",
    "asked": 0,
    "fetched": 0,
    "written": 0,
    "skipped": 0,
    "unreadable": 0,
    "lagged": 0,
    "cursor": "2026-08-06T17:22:45Z",
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
        lambda _request, wiki, **kwargs: asked.append(kwargs["watch_limit"]) or dict(WATCHED, wiki=wiki),
    )
    assert job.main() == 0
    assert asked == [expected]


def test_a_watch_reports_the_wiki_time_it_has_caught_up_to(monkeypatch, capsys, _job_env):
    # The number that separates a quiet hour from a census weeks behind. Both
    # write nothing and print the same five zeros; only the cursor says which
    # one just happened.
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")
    monkeypatch.setattr(job.userscript_sweep, "run", lambda _request, wiki, **_kwargs: dict(WATCHED, wiki=wiki))
    assert job.main() == 0
    out = capsys.readouterr().out
    assert "mode=watch" in out
    assert "cursor=2026-08-06T17:22:45Z" in out


def test_a_watch_that_has_never_run_says_so_rather_than_printing_a_blank(monkeypatch, capsys, _job_env):
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")
    monkeypatch.setattr(job.userscript_sweep, "run", lambda _request, wiki, **_kwargs: dict(WATCHED, wiki=wiki, cursor=""))
    assert job.main() == 0
    assert "cursor=none" in capsys.readouterr().out


def test_one_wikis_failure_does_not_cost_the_next_wiki_its_turn(monkeypatch, capsys, _job_env):
    # The 2026-08-23 outage: a Meta page raised out of ingest, enwiki was third
    # in the list, and enwiki's first sweep stopped advancing for three runs
    # until the guard disabled the job. Ordering decided which corpus starved.
    covered = []

    def run(_request, wiki, **_kwargs):
        if wiki == "meta.wikimedia.org":
            raise RuntimeError("Duplicate entry for key 'wiki'")
        covered.append(wiki)
        return dict(SWEPT, wiki=wiki)

    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org,meta.wikimedia.org,en.wikipedia.org")
    monkeypatch.setattr(job.userscript_sweep, "run", run)
    # Still a failure -- a wiki that could not be covered is one the guard
    # should count, and `job_runner` signals that by letting it out -- but not
    # before every other wiki has had its run.
    with pytest.raises(job.CensusIncompleteError, match="census failed for meta.wikimedia.org"):
        job.main()
    assert covered == ["fr.wikipedia.org", "en.wikipedia.org"]
    out = capsys.readouterr().out
    assert "wiki=meta.wikimedia.org failed error=RuntimeError" in out


def test_two_loads_the_database_calls_one_do_not_fail_the_page():
    # The 2026-08-23 crash. MySQL folds case and invisible marks where Python
    # does not, so a page can offer two loads that are one row to the database
    # -- Meta's User:.../global.js loads both `MediaWiki:Gadget-x.js` and
    # `Mediawiki:gadget-x.js`. SQLite compares bytes and cannot be made to fold
    # anything, so the collision is stated at the level the fix works at: two
    # entries that the unique key cannot tell apart. Whatever a real collation
    # merges arrives here looking exactly like this.
    twice = userscripts.ScriptImport(
        verb="mw.loader.load",
        argument="//ar.wikipedia.org/x",
        wiki="ar.wikipedia.org",
        title="MediaWiki:Gadget-x.js",
        url="//ar.wikipedia.org/x",
    )
    analysis = userscripts.ScriptPage(
        title="User:A/global.js",
        role="loader",
        fingerprint="f",
        imports=(twice, twice),
    )
    with db.session_scope() as session:
        sweeper._replace_imports(session, FRWIKI, analysis)
    with db.session_scope() as session:
        stored = session.query(UserScriptImport).filter(UserScriptImport.wiki == FRWIKI).all()
    # One row, no exception -- and in particular the page's other work is not
    # rolled back with the row the database refused.
    assert [(row.source_title, row.target_title) for row in stored] == [
        ("User:A/global.js", "MediaWiki:Gadget-x.js"),
    ]


def test_a_page_loading_several_modules_stores_one_row_each():
    # Every module edge has a blank wiki, title and URL, so the module name is
    # the only thing keeping them apart under the table's unique key.
    imports = tuple(
        userscripts.ScriptImport(verb="mw.loader.load", argument=name, wiki=FRWIKI, module=name)
        for name in ("ext.gadget.A", "ext.gadget.B", "ext.gadget.C")
    )
    analysis = userscripts.ScriptPage(title="User:A/common.js", role="loader", fingerprint="f", imports=imports)
    with db.session_scope() as session:
        sweeper._replace_imports(session, FRWIKI, analysis)
    with db.session_scope() as session:
        stored = session.query(UserScriptImport).filter(UserScriptImport.wiki == FRWIKI).all()
    assert sorted(row.target_module for row in stored) == ["ext.gadget.A", "ext.gadget.B", "ext.gadget.C"]
    assert {row.target_title for row in stored} == {""}
