"""Tests for reading a wiki's user scripts into the directory."""

import sys
from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_census as census, userscript_sweep as sweeper  # noqa: E402
from backend import userscripts, wiki_replica  # noqa: E402
from backend.models import UserScriptCensusState, UserScriptImport, UserScriptPage, utcnow  # noqa: E402

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


class TooLarge(RuntimeError):
    """The client refusing an answer for its size, carrying the code it uses.

    A separate class from `Boom` because the whole point is that the census can
    tell them apart, and it tells them apart by the code -- so a fake that
    raised one class for both would let the distinction pass untested.
    """

    code = sweeper.ERROR_RESPONSE_TOO_LARGE


class FakeWiki:
    """An Action API that answers from a dict of pages, and can be made to fail."""

    def __init__(
        self,
        pages,
        *,
        changes=None,
        unreadable=(),
        too_large=(),
        page_size=None,
        lagged_after=None,
        namespace_name="User",
        namespace_aliases=(),
    ):
        # title -> (model, body, revid, timestamp)
        self.pages = dict(pages)
        self.changes = list(changes or [])
        self.unreadable = set(unreadable)
        #: Titles the wiki answers for only when asked for alone -- and not even
        #: then. Any request naming one is refused for size, which is what the
        #: real client does: it measures the response, so a batch holding a
        #: two-megabyte page is refused whatever else is in it.
        self.too_large = set(too_large)
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
            return self._changes(params)
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
        if any(title in self.too_large for title in asked):
            raise TooLarge(params["titles"])
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

    def _changes(self, params):
        """Serve one window of the feed, and offer the next the way the API does.

        `rcstart` is recorded rather than applied -- the tests that care about it
        assert on `requests`, and filtering here would silently drop the fixture
        timestamps the older tests were written around. The continuation is real,
        because a watch that follows it is the thing being tested: `rccontinue`
        carries the offset, and its absence is how the feed says it is exhausted.
        """
        start = int(params.get("rccontinue") or 0)
        window = self.changes[start : start + int(params.get("rclimit") or len(self.changes))]
        answer = {"query": {"recentchanges": window}}
        if start + len(window) < len(self.changes):
            answer["continue"] = {"rccontinue": str(start + len(window)), "continue": "-||"}
        return answer

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
            "sketch": row.sketch,
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
    read, unreadable, _big, _lagged = sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js", "User:Gone/x.js"])
    assert [found.title for found in read] == ["User:A/one.js"]
    assert unreadable == 0


def test_a_failed_batch_is_retried_one_title_at_a_time():
    wiki = FakeWiki(
        {"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")},
        unreadable={"User:B/two.js"},
    )
    read, unreadable, _big, _lagged = sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js", "User:B/two.js"])
    # The whole batch failed on one page, and splitting rescued the other.
    assert [found.title for found in read] == ["User:A/one.js"]
    assert unreadable == 1


def test_a_fat_batch_is_halved_rather_than_taken_apart_title_by_title():
    # This is what lets `CONTENT_BATCH` be set by what the API will answer
    # rather than by what a bad batch costs to recover from: one page too big
    # for the response cap costs a handful of extra requests, not one per title.
    titles = [f"User:U{index}/x.js" for index in range(8)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, unreadable={"User:U5/x.js"})
    read, unreadable, _big, _lagged = sweeper.read_titles(wiki.request, FRWIKI, titles)
    assert [found.title for found in read] == [title for title in titles if title != "User:U5/x.js"]
    assert unreadable == 1
    asked = [params["titles"].split("|") for _d, _m, params in wiki.requests]
    # The halves are visible in the sizes asked for, and only the pair either
    # side of the unreadable page was ever read alone: seven requests where
    # falling straight to single titles would have cost nine.
    assert sorted(len(batch) for batch in asked) == [1, 1, 2, 2, 4, 4, 8]


# -- pages no request can carry -----------------------------------------


def test_a_page_too_big_to_fetch_is_counted_apart_from_one_that_merely_failed():
    # Both are pages this run does not have, and only one of them is worth
    # looking at. A transport blip may well succeed next run; a page past the
    # response cap will say the same thing every run until someone shrinks it,
    # and counting the two together is what makes `unreadable` a number nobody
    # reads.
    titles = ["User:A/one.js", "User:Big/list.js", "User:C/three.js"]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, too_large={"User:Big/list.js"})
    read, unreadable, oversized, _lagged = sweeper.read_titles(wiki.request, FRWIKI, titles)
    assert [found.title for found in read] == ["User:A/one.js", "User:C/three.js"]
    assert oversized == 1
    assert unreadable == 0


def test_a_transport_failure_is_still_unreadable_rather_than_oversized():
    # The discrimination is the client's code, not the shape of the failure --
    # so a refusal that carries no code must not be promoted into the permanent
    # category just because it happened to a single title.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")}, unreadable={"User:A/one.js"})
    read, unreadable, oversized, _lagged = sweeper.read_titles(wiki.request, FRWIKI, ["User:A/one.js"])
    assert read == []
    assert (unreadable, oversized) == (1, 0)


def test_a_page_known_too_big_is_asked_for_alone_instead_of_failing_a_batch():
    # The second meeting is the one that matters: without a memo the census
    # pays the whole halving search again to rediscover a page it has already
    # proven it cannot read.
    titles = [f"User:U{index}/x.js" for index in range(8)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles}, too_large={"User:U5/x.js"})
    known: set[str] = set()

    sweeper.read_titles(wiki.request, FRWIKI, titles, known)
    first = len(wiki.requests)
    assert known == {"User:U5/x.js"}

    wiki.requests.clear()
    read, unreadable, oversized, _lagged = sweeper.read_titles(wiki.request, FRWIKI, titles, known)
    # Everything readable still arrives, and the verdict is still reported --
    # the page is asked for, because a page can shrink and a memo that stopped
    # asking could never find out.
    assert [found.title for found in read] == [title for title in titles if title != "User:U5/x.js"]
    assert (unreadable, oversized) == (0, 1)
    asked = sorted(len(params["titles"].split("|")) for _d, _m, params in wiki.requests)
    # The seven good pages in one request, the known-bad one in its own.
    assert asked == [1, 7]
    assert len(wiki.requests) < first


def test_one_page_over_the_cap_does_not_spend_the_split_budget_twice_in_a_run():
    # What the enwiki watch actually meets: a bot-maintained list past the
    # response cap, edited daily, so a run catching up over several days finds
    # it in more than one window.
    fat = "User:NovemBot/userlist.js"
    pages = {fat: page("var a = 1;"), "User:A/one.js": page("var b = 2;")}
    wiki = FakeWiki(
        pages,
        changes=[
            {"title": fat, "ns": 2, "timestamp": "2026-01-01T00:00:00Z"},
            {"title": "User:A/one.js", "ns": 2, "timestamp": "2026-01-01T01:00:00Z"},
            {"title": fat, "ns": 2, "timestamp": "2026-01-02T00:00:00Z"},
        ],
        too_large={fat},
    )
    summary = sweeper.watch(wiki.request, FRWIKI, limit=1)
    # Seen in two windows, so counted twice -- the count is of reads that came
    # back empty, and there were two of them.
    assert summary["oversized"] == 2
    assert summary["unreadable"] == 0
    # But asked for alone the second time: every content request names one page,
    # and none of them is the halving search running twice.
    content = [params["titles"] for _d, _m, params in wiki.requests if "titles" in params]
    assert all("|" not in asked for asked in content)


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
    read, unreadable, _big, lagged = sweeper.read_titles(wiki.request, FRWIKI, titles)
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


def test_a_run_carries_every_page_collision_up_into_its_summary(monkeypatch):
    # The count has to survive two hops -- `_replace_imports` to `store_page` to
    # the run's summary -- and the collation that produces one cannot be
    # reproduced on SQLite, which compares bytes. So the collision is injected
    # and what is asserted is the carrying, which is the part that breaks.
    monkeypatch.setattr(sweeper, "_replace_imports", lambda *_args: 2)
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")})
    summary = sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js", "User:B/two.js"], ranked=True)
    assert summary["written"] == 2
    assert summary["collisions"] == 4


def test_a_run_with_nothing_to_drop_reports_no_collisions():
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    assert sweeper.ingest(wiki.request, FRWIKI, ["User:A/one.js"], ranked=True)["collisions"] == 0


# --- holding one slice at a time ---


def test_a_window_is_read_one_slice_at_a_time_however_large_it_is(monkeypatch):
    # The invariant enwiki broke. A run reading its whole window before writing
    # any of it held twenty thousand page bodies at once and was killed for it,
    # leaving no traceback -- so what is asserted here is the shape of the reads,
    # not the memory, because the memory is only ever observable as a dead pod.
    titles = [f"User:U{index:03d}/x.js" for index in range(census.CONTENT_BATCH * 4)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles})
    monkeypatch.setattr(sweeper, "INGEST_CHUNK", census.CONTENT_BATCH)
    asked = []
    real_read = sweeper.read_titles
    monkeypatch.setattr(
        sweeper,
        "read_titles",
        lambda request, wiki_name, slice_, known=None: (
            asked.append(len(slice_)),
            real_read(request, wiki_name, slice_, known),
        )[1],
    )

    summary = sweeper.ingest(wiki.request, FRWIKI, titles, ranked=True)

    assert max(asked) <= sweeper.INGEST_CHUNK
    # Sliced, and still the whole window: bounding the hold must not bound the run.
    assert summary["written"] == len(titles)
    assert summary["fetched"] == len(titles)


def test_a_run_killed_part_way_keeps_the_pages_it_already_wrote(monkeypatch):
    # A memory limit kills the process outright. Nothing catches that and
    # nothing commits on the way out, so the only writes that survive are the
    # ones a slice already committed -- which is the second half of why the
    # window is sliced at all.
    titles = [f"User:U{index:03d}/x.js" for index in range(census.CONTENT_BATCH * 4)]
    wiki = FakeWiki({title: page("var a = 1;") for title in titles})
    monkeypatch.setattr(sweeper, "INGEST_CHUNK", census.CONTENT_BATCH)
    real_request = wiki.request

    def killed(domain, method, params):
        if wiki.content_requests >= 2:
            raise KeyboardInterrupt("the container ran out of memory")
        return real_request(domain, method, params)

    with pytest.raises(KeyboardInterrupt):
        sweeper.ingest(killed, FRWIKI, titles, ranked=True)

    assert stored("User:U000/x.js") is not None
    with db.session_scope() as session:
        assert session.query(UserScriptPage).count() == census.CONTENT_BATCH * 2


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
    read, unreadable, _big, _lagged = sweeper.read_titles(wiki.request, FRWIKI, titles)
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
    # Stored alongside the fingerprint rather than derived on read: the fold runs
    # in a process that never sees a body, and re-sampling 155,000 of them per
    # directory run would cost more than the column.
    assert row["sketch"] == userscripts.sketch(row["body"])
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
    recorded = state()
    # Stamped from the clock, so it is asserted for shape by the tests that own
    # it rather than compared to a literal here.
    assert recorded.pop("cursor") != ""
    assert recorded == {
        "sweeps": 1,
        "pages": 3,
        "scripts": 1,
        "imports": 1,
        "complete": True,
        "totals": {"javascript": 2, "css": 1},
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
    assert summary["windows"] == 1
    assert summary["behind"] == 0
    # The window budget costs a caught-up wiki nothing: the feed offers no
    # continuation, so the loop stops after the window it was always going to read.
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


# -- catching up --------------------------------------------------------


def test_a_completed_sweep_leaves_a_cursor_so_the_first_watch_does_not_start_a_month_back():
    # Without one, `changes_params` sends no `rcstart`, and `rcdir=newer` starts
    # the feed at the oldest row recent changes still keeps. A wiki fresh from a
    # complete sweep began watching a month in the past, re-reading a month of
    # edits to pages the sweep had just read. That is what put enwiki 30 days
    # behind on 2026-08-24.
    wiki = FakeWiki({"User:A/one.js": page("var a = 1;")})
    began = census.api_timestamp(utcnow())
    sweeper.sweep(wiki.request, FRWIKI)
    assert state()["cursor"] >= began
    sweeper.watch(wiki.request, FRWIKI)
    feeds = [params for _domain, _method, params in wiki.requests if params.get("list") == "recentchanges"]
    assert feeds[-1]["rcstart"] >= began


def test_the_cursor_a_sweep_leaves_is_where_the_pass_began_not_where_it_ended():
    # A bounded sweep spans runs, and a page read in the first run can be edited
    # before the last one ends. A cursor stamped when the pass finished would
    # step straight over that edit, and a watch has no second pass to find it.
    wiki = FakeWiki(THREE)
    sweeper.run(wiki.request, FRWIKI, limit=1)
    seeded = state()["cursor"]
    assert seeded != ""
    for _run in range(2):
        sweeper.run(wiki.request, FRWIKI, limit=1)
    assert state()["sweeps"] == 1
    assert state()["cursor"] == seeded


def behind_by(days):
    """A wiki whose feed holds one changed script page per day."""
    return FakeWiki(
        {f"User:A/s{index}.js": page(f"var a = {index};") for index in range(days)},
        changes=[
            {"ns": 2, "title": f"User:A/s{index}.js", "timestamp": f"2026-01-{index + 1:02d}T00:00:00Z"}
            for index in range(days)
        ],
    )


def test_a_watch_that_is_behind_follows_the_feed_rather_than_reading_one_window():
    # One window per run only converges while the wiki produces fewer changes
    # per run than a window holds. enwiki's user namespace does not, so the
    # census gained half an hour per hour and never caught up.
    summary = sweeper.watch(behind_by(10).request, FRWIKI, limit=3)
    assert summary["windows"] == 4
    assert summary["behind"] == 0
    assert summary["asked"] == 10
    assert summary["cursor"] == "2026-01-10T00:00:00Z"


def test_a_watch_that_runs_out_of_windows_says_it_is_still_behind():
    # Every other count on the line reads the same as a quiet hour. Without this
    # one, a census weeks behind and a wiki nobody edited are indistinguishable.
    summary = sweeper.watch(behind_by(10).request, FRWIKI, limit=3, windows=2)
    assert summary["windows"] == 2
    assert summary["behind"] == 1
    assert summary["asked"] == 6
    assert summary["cursor"] == "2026-01-06T00:00:00Z"


def test_the_run_after_a_budget_ran_out_resumes_from_the_cursor_rather_than_the_start():
    wiki = behind_by(10)
    sweeper.watch(wiki.request, FRWIKI, limit=3, windows=2)
    sweeper.watch(wiki.request, FRWIKI, limit=3, windows=2)
    feeds = [params for _domain, _method, params in wiki.requests if params.get("list") == "recentchanges"]
    # A first window with nothing to resume from, then the feed's own
    # continuation within the run, then the next run picking the cursor back up.
    assert "rcstart" not in feeds[0]
    assert feeds[1]["rccontinue"] == "3"
    assert feeds[2]["rcstart"] == "2026-01-06T00:00:00Z"


def test_a_watch_cut_short_by_lag_keeps_the_windows_it_already_finished():
    # The windows before the refusal were read in full. Dropping them back to
    # where the run started would re-read work that was done, which on a wiki
    # spending every run catching up is the difference between converging and not.
    wiki = FakeWiki(
        {"User:A/one.js": page("var a = 1;"), "User:B/two.js": page("var b = 2;")},
        changes=[
            {"ns": 2, "title": "User:A/one.js", "timestamp": "2026-01-02T00:00:00Z"},
            {"ns": 2, "title": "User:B/two.js", "timestamp": "2026-01-03T00:00:00Z"},
        ],
        lagged_after=1,
    )
    summary = sweeper.watch(wiki.request, FRWIKI, limit=1)
    assert summary["lagged"] == 1
    assert summary["windows"] == 1
    assert summary["cursor"] == "2026-01-02T00:00:00Z"


def test_one_refusal_is_one_lagged_flag_however_many_windows_a_run_read():
    # `lagged` says the run was cut short. It is a fact about the run, not a
    # tally, and summing it across windows would print a count of something
    # there is only one of.
    wiki = behind_by(4)
    wiki.lagged_after = 2
    summary = sweeper.watch(wiki.request, FRWIKI, limit=1)
    assert summary["lagged"] == 1


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
    "oversized": 0,
    "lagged": 0,
    "collisions": 0,
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
    "oversized": 0,
    "lagged": 0,
    "collisions": 0,
    "cursor": "2026-08-06T17:22:45Z",
    "windows": 1,
    "behind": 0,
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
    assert seen[0][1] == {
        "full": False,
        "limit": 0,
        "watch_limit": sweeper.WATCH_LIMIT,
        "watch_windows": sweeper.WATCH_WINDOWS,
    }
    out = capsys.readouterr().out
    assert "userscript-census: wiki=fr.wikipedia.org mode=sweep" in out
    assert "unreadable=0" in out


def test_the_census_line_reports_collisions_only_when_there_were_some(monkeypatch, capsys, _job_env):
    # Nonzero is the whole reason the field exists, and zero is the reason it is
    # not always printed: a field that reads 0 on every line of every run is a
    # field readers stop seeing, including on the run where it finally is not 0.
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **_kwargs: dict(SWEPT, wiki=wiki, written=2, collisions=3),
    )
    assert job.main() == 0
    assert "collisions=3" in capsys.readouterr().out

    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **_kwargs: dict(SWEPT, wiki=wiki, written=2),
    )
    assert job.main() == 0
    assert "collisions" not in capsys.readouterr().out


def test_the_census_line_reports_oversized_only_when_there_were_some(monkeypatch, capsys, _job_env):
    # Same rule as `collisions`, for the same reason -- but with a sharper edge
    # here, because this one has a standing cause: enwiki has a bot-maintained
    # list that has been past the response cap for months. Printed every run it
    # would read as an incident every run.
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **_kwargs: dict(SWEPT, wiki=wiki, oversized=1),
    )
    assert job.main() == 0
    assert "oversized=1" in capsys.readouterr().out

    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **_kwargs: dict(SWEPT, wiki=wiki),
    )
    assert job.main() == 0
    assert "oversized" not in capsys.readouterr().out


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
    assert asked == [{"full": True, "limit": 40, "watch_limit": 80, "watch_windows": sweeper.WATCH_WINDOWS}]


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


@pytest.mark.parametrize(("raw", "expected"), [("", 48), ("nonsense", 48), ("-5", 48), ("0", 48), ("6", 6)])
def test_an_unusable_window_budget_falls_back_to_the_default(monkeypatch, raw, expected, _job_env):
    asked = []
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")  # one wiki: this is about the options, not the list
    monkeypatch.setenv("USERSCRIPT_WATCH_WINDOWS", raw)
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **kwargs: asked.append(kwargs["watch_windows"]) or dict(WATCHED, wiki=wiki),
    )
    assert job.main() == 0
    assert asked == [expected]


def test_a_watch_says_how_many_windows_it_got_through(monkeypatch, capsys, _job_env):
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **_kwargs: dict(WATCHED, wiki=wiki, windows=12),
    )
    assert job.main() == 0
    out = capsys.readouterr().out
    assert "windows=12" in out
    # Not behind, so the line does not carry the field at all -- same rule as
    # `collisions`: a field that reads 0 every run is one readers stop seeing.
    assert "behind" not in out


def test_a_watch_that_used_its_whole_budget_says_it_is_still_behind(monkeypatch, capsys, _job_env):
    # The one number that separates a census weeks behind from a quiet hour once
    # the cursor is close enough to look reasonable on its own.
    monkeypatch.setenv("USERSCRIPT_WIKIS", "fr.wikipedia.org")
    monkeypatch.setattr(
        job.userscript_sweep,
        "run",
        lambda _request, wiki, **_kwargs: dict(WATCHED, wiki=wiki, windows=48, behind=1),
    )
    assert job.main() == 0
    assert "windows=48 behind=1" in capsys.readouterr().out


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
    # No longer a failed run either, which is the other half of that lesson and
    # a deliberate change of contract. With three wikis, one unreachable meant
    # something was wrong and the guard was right to escalate. Now that the
    # queue covers every readable Wikimedia wiki, some wiki is always having a
    # bad day, and a run that failed for it would have the guard disable the
    # whole census within three ticks -- starving the other thousand corpora
    # for one wiki's afternoon. The failure is recorded on the wiki instead.
    assert job.main() == 0
    assert covered == ["fr.wikipedia.org", "en.wikipedia.org"]
    out = capsys.readouterr().out
    assert "wiki=meta.wikimedia.org failed error=RuntimeError" in out
    assert "userscript-census: queued=3 covered=2 failed=1" in out


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
        sketch="",
        imports=(twice, twice),
    )
    with db.session_scope() as session:
        dropped = sweeper._replace_imports(session, FRWIKI, analysis)
    with db.session_scope() as session:
        stored = session.query(UserScriptImport).filter(UserScriptImport.wiki == FRWIKI).all()
    # One row, no exception -- and in particular the page's other work is not
    # rolled back with the row the database refused.
    assert [(row.source_title, row.target_title) for row in stored] == [
        ("User:A/global.js", "MediaWiki:Gadget-x.js"),
    ]
    # And the drop is reported. Letting the database decide what a duplicate is
    # means this codebase cannot know how many there were without asking, so the
    # one thing it must not do is fold them away in silence.
    assert dropped == 1


def test_restating_an_analysis_leaves_every_record_of_reading_the_wiki_alone():
    # The correction comes out of the stored body, and no wiki was asked. A row
    # that moved `last_checked_at` here would report a freshness it never earned,
    # and one that moved `revision` would tell the next sweep it had already read
    # a revision it has not seen.
    body = "// @match https://commons.wikimedia.org/*\n" + "".join(f"var a{at} = {at};\n" for at in range(40))
    checked = datetime(2024, 3, 1, 12, 0, 0)
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki=FRWIKI,
                title="User:A/one.js",
                role="empty",
                body=body,
                revision="7",
                last_checked_at=checked,
                touched_at_wiki="2024-01-01T00:00:00Z",
            ),
        )
    with db.session_scope() as session:
        row = session.query(UserScriptPage).one()
        assert sweeper.restate_analysis(session, row) is True
    with db.session_scope() as session:
        row = session.query(UserScriptPage).one()
        assert row.role == userscripts.ROLE_SCRIPT
        assert (row.revision, row.last_checked_at, row.touched_at_wiki) == ("7", checked, "2024-01-01T00:00:00Z")


def test_restating_an_analysis_that_has_not_changed_reports_no_repair():
    body = "".join(f"var a{at} = {at};\n" for at in range(40))
    analysis = userscripts.analyze("User:A/one.js", body, wiki=FRWIKI)
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki=FRWIKI,
                title="User:A/one.js",
                role=analysis.role,
                fingerprint=analysis.fingerprint,
                sketch=analysis.sketch,
                body=body,
            ),
        )
    with db.session_scope() as session:
        row = session.query(UserScriptPage).one()
        assert sweeper.restate_analysis(session, row) is False


def test_restating_a_body_stored_at_the_truncation_cap_is_declined():
    # `store_page` derives the analysis from the whole page and keeps only the
    # first `MAX_STORED_BODY` characters, so what is on the row here is a verdict
    # about text this function cannot see. Restating from the remnant would
    # replace it with a narrower claim wearing the same fields.
    body = "// @match https://commons.wikimedia.org/*\n" + ("x" * sweeper.MAX_STORED_BODY)
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki=FRWIKI,
                title="User:A/huge.js",
                role="empty",
                fingerprint="from-the-whole-page",
                body=body[: sweeper.MAX_STORED_BODY],
            ),
        )
    with db.session_scope() as session:
        row = session.query(UserScriptPage).one()
        assert sweeper.restate_analysis(session, row) is False
    with db.session_scope() as session:
        row = session.query(UserScriptPage).one()
        assert (row.role, row.fingerprint) == ("empty", "from-the-whole-page")


def test_a_page_whose_loads_all_survive_reports_no_collisions():
    imports = tuple(
        userscripts.ScriptImport(
            verb="mw.loader.load",
            argument=f"//ar.wikipedia.org/{name}",
            wiki="ar.wikipedia.org",
            title=f"MediaWiki:Gadget-{name}.js",
            url=f"//ar.wikipedia.org/{name}",
        )
        for name in ("a", "b")
    )
    analysis = userscripts.ScriptPage(
        title="User:A/global.js", role="loader", fingerprint="f", sketch="", imports=imports
    )
    with db.session_scope() as session:
        assert sweeper._replace_imports(session, FRWIKI, analysis) == 0


def test_a_page_loading_several_modules_stores_one_row_each():
    # Every module edge has a blank wiki, title and URL, so the module name is
    # the only thing keeping them apart under the table's unique key.
    imports = tuple(
        userscripts.ScriptImport(verb="mw.loader.load", argument=name, wiki=FRWIKI, module=name)
        for name in ("ext.gadget.A", "ext.gadget.B", "ext.gadget.C")
    )
    analysis = userscripts.ScriptPage(
        title="User:A/common.js", role="loader", fingerprint="f", sketch="", imports=imports
    )
    with db.session_scope() as session:
        sweeper._replace_imports(session, FRWIKI, analysis)
    with db.session_scope() as session:
        stored = session.query(UserScriptImport).filter(UserScriptImport.wiki == FRWIKI).all()
    assert sorted(row.target_module for row in stored) == ["ext.gadget.A", "ext.gadget.B", "ext.gadget.C"]
    assert {row.target_title for row in stored} == {""}
