# SPDX-License-Identifier: GPL-3.0-or-later
"""Read endpoints over a wiki's user-script directory: listing, one script, coverage."""

from datetime import datetime

import pytest
from flask import Flask

import backend
from backend import db, security, userscript_directory as directory, userscript_projection as projection
from backend.models import UserScriptCensusState, UserScriptImport, UserScriptPage, utcnow

FRWIKI = "fr.wikipedia.org"
ENWIKI = "en.wikipedia.org"


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def page(title, *, rank=0, role="script", fingerprint="", wiki=FRWIKI):
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki=wiki,
                title=title,
                owner=directory.owner_of_user_page(title),
                basename=directory.basename_of(title),
                role=role,
                fingerprint=fingerprint,
                discovery_rank=rank,
            ),
        )


def loads(source, target, *, wiki=FRWIKI):
    with db.session_scope() as session:
        session.add(
            UserScriptImport(wiki=wiki, source_title=source, verb="importScript", target_title=target),
        )


def identity(title, wiki=FRWIKI):
    """The census id of one page -- the identity the endpoints hand back."""
    with db.session_scope() as session:
        return (
            session.query(UserScriptPage.id)
            .filter(UserScriptPage.wiki == wiki, UserScriptPage.title == title)
            .scalar()
        )


def corpus():
    """A small frwiki: one popular script with a fork, one nobody loads."""
    page("User:Aaa/popular.js", rank=0, fingerprint="copy")
    page("User:Bbb/popular.js", rank=1, fingerprint="copy")
    page("User:Ccc/popular.js", rank=2, fingerprint="copy")
    page("User:Ddd/quiet.js", rank=3)
    for who in ["Eee", "Fff"]:
        loads(f"User:{who}/common.js", "User:Aaa/popular.js")
    projection.project(FRWIKI)


def two_wikis():
    """Two wikis, including a script on each that ties the other on demand."""
    corpus()
    page("User:Zzz/popular.js", rank=0, wiki=ENWIKI)
    page("User:Www/tied.js", rank=1, wiki=ENWIKI)
    page("User:Yyy/mid.js", rank=2, wiki=ENWIKI)
    for who in ["Ggg", "Hhh", "Iii"]:
        loads(f"User:{who}/common.js", "User:Zzz/popular.js", wiki=ENWIKI)
    for who in ["Kkk", "Lll"]:
        loads(f"User:{who}/common.js", "User:Www/tied.js", wiki=ENWIKI)
    loads("User:Jjj/common.js", "User:Yyy/mid.js", wiki=ENWIKI)
    projection.project(ENWIKI)


def test_omitting_the_wiki_reads_every_wiki_at_once(app, client):
    # A wiki used to be required. It is optional now because the directory covers
    # close to a thousand projects and no single one of them is the obvious place
    # for an unqualified visit to open.
    with app.app_context():
        two_wikis()
    body = client.get("/v1/userscripts/directory/").get_json()
    assert body["wiki"] == ""
    assert {row["wiki"] for row in body["results"]} == {FRWIKI, ENWIKI}
    assert body["total"] == len(body["results"]) == 4


def test_a_cross_wiki_reading_is_ranked_by_demand_not_by_per_wiki_position(app, client):
    # Every wiki has a script at position 1, so ordering the union by `position`
    # would interleave one ladder per wiki. The order has to come from `demand`.
    with app.app_context():
        two_wikis()
    body = client.get("/v1/userscripts/directory/").get_json()
    assert [row["demand"] for row in body["results"]] == [3, 2, 2, 1]
    assert {row["wiki"] for row in body["results"]} == {ENWIKI, FRWIKI}
    # The two rows tied at 2 sit on different wikis, and which of them wins the
    # tie is arbitrary. What is not arbitrary is that it wins it every time --
    # otherwise a reader paging through would see one row twice and miss one.
    again = client.get("/v1/userscripts/directory/").get_json()
    assert [row["title"] for row in again["results"]] == [row["title"] for row in body["results"]]
    # Each wiki's own ranking is still reported, and is exactly what could not
    # have produced this order: two rows here both hold first place at home.
    assert sorted(row["position"] for row in body["results"]) == [1, 1, 2, 3]


def test_cross_wiki_paging_does_not_repeat_or_skip_a_row(app, client):
    # Ties on `demand` are broken by wiki then title, so a row cannot drift
    # between pages the way an order with ties can.
    with app.app_context():
        two_wikis()
    walked = []
    for offset in range(0, 4):
        page_body = client.get(f"/v1/userscripts/directory/?limit=1&offset={offset}").get_json()
        walked += [(row["wiki"], row["title"]) for row in page_body["results"]]
    assert len(set(walked)) == 4
    whole = client.get("/v1/userscripts/directory/").get_json()
    assert walked == [(row["wiki"], row["title"]) for row in whole["results"]]


def test_a_cross_wiki_reading_still_answers_tier_and_owner(app, client):
    with app.app_context():
        two_wikis()
    archive = client.get("/v1/userscripts/directory/?tier=archive").get_json()
    assert [row["title"] for row in archive["results"]] == ["User:Ddd/quiet.js"]
    owned = client.get("/v1/userscripts/directory/?owner=Zzz").get_json()
    assert [(row["wiki"], row["owner"]) for row in owned["results"]] == [(ENWIKI, "Zzz")]


def test_a_cross_wiki_reading_discloses_no_single_wiki_coverage(app, client):
    # There is no one sweep to describe, and averaging a thousand of them would
    # state something true of no wiki. Say nothing rather than say something
    # invented; the caller already holds the per-wiki records from /wikis/.
    with app.app_context():
        two_wikis()
    assert client.get("/v1/userscripts/directory/").get_json()["coverage"] is None
    assert client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}").get_json()["coverage"]["wiki"] == FRWIKI


def test_listing_rejects_an_unknown_tier(client):
    body = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&tier=maybe").get_json()
    assert "tier must be one of" in body["error"]


def test_listing_returns_the_active_tier_in_rank_order(app, client):
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}").get_json()
    assert body["tier"] == directory.TIER_ACTIVE
    assert [row["title"] for row in body["results"]] == ["User:Aaa/popular.js"]
    assert body["results"][0]["demand"] == 2
    assert body["results"][0]["position"] == 1
    assert body["total"] == 1


def test_the_archive_tier_is_asked_for_by_name(app, client):
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&tier=archive").get_json()
    assert [row["title"] for row in body["results"]] == ["User:Ddd/quiet.js"]


def test_a_listing_can_be_narrowed_to_one_owner(app, client):
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&tier=archive&owner=Ddd").get_json()
    assert body["total"] == 1
    empty = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&tier=archive&owner=Nobody").get_json()
    assert empty["total"] == 0


def test_paging_walks_the_ranking_without_repeating_it(app, client):
    with app.app_context():
        for index in range(5):
            page(f"User:P{index}/tool.js", rank=index)
            for who in range(5 - index):
                loads(f"User:R{index}{who}/common.js", f"User:P{index}/tool.js")
        projection.project(FRWIKI)
    first = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&limit=2").get_json()
    second = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&limit=2&offset=2").get_json()
    assert [row["position"] for row in first["results"]] == [1, 2]
    assert [row["position"] for row in second["results"]] == [3, 4]
    assert first["total"] == second["total"] == 5


def test_nonsense_paging_falls_back_instead_of_failing(app, client):
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&limit=abc&offset=-9").get_json()
    assert (body["limit"], body["offset"]) == (25, 0)


def test_an_oversized_limit_is_capped(app, client):
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}&limit=99999").get_json()
    assert body["limit"] == 200


def test_an_unswept_wiki_says_so_rather_than_looking_empty(app, client):
    # The whole point of the coverage block: nothing here may read as
    # "this wiki has no user scripts".
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/directory/?wiki={ENWIKI}").get_json()
    assert body["results"] == []
    assert body["coverage"] == {
        "wiki": ENWIKI,
        "pages": 0,
        "sweepsCompleted": 0,
        "sweptAt": "",
        "currentTo": "",
        "checkedAt": "",
        "enumerated": True,
        "enumeratedBy": "",
        "computedAt": "",
        "active": 0,
        "archive": 0,
    }


def test_coverage_reports_the_sweep_behind_the_directory(app, client):
    with app.app_context():
        corpus()
        with db.session_scope() as session:
            session.add(
                UserScriptCensusState(
                    wiki=FRWIKI,
                    sweeps_completed=2,
                    last_started_at=utcnow(),
                    last_success_at=utcnow(),
                )
            )
    disclosed = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}").get_json()["coverage"]
    assert disclosed["sweepsCompleted"] == 2
    assert disclosed["sweptAt"].endswith("Z")
    assert disclosed["computedAt"].endswith("Z")
    assert (disclosed["pages"], disclosed["active"], disclosed["archive"]) == (4, 1, 1)
    assert disclosed["enumerated"] is True


def test_a_live_job_over_a_stale_census_is_not_reported_as_a_fresh_directory(app, client):
    # frwiki, exactly: swept once on 21 July, watched successfully every hour
    # since, and reading recent changes from 6 August. One timestamp -- the one
    # the hourly run stamps -- would have called this current.
    with app.app_context():
        corpus()
        with db.session_scope() as session:
            session.add(
                UserScriptCensusState(
                    wiki=FRWIKI,
                    sweeps_completed=1,
                    last_started_at=datetime(2026, 7, 21, 8, 23, 11),
                    last_success_at=utcnow(),
                    changes_cursor="2026-08-06T17:22:45Z",
                    enumeration_source="search",
                )
            )
    disclosed = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}").get_json()["coverage"]
    assert disclosed["sweptAt"].startswith("2026-07-21")
    assert disclosed["currentTo"] == "2026-08-06T17:22:45Z"
    assert disclosed["checkedAt"] > disclosed["sweptAt"]
    assert disclosed["enumeratedBy"] == "search"


def test_coverage_admits_a_wiki_too_large_to_enumerate_in_one_pass(app, client):
    # A finished sweep of a wiki whose search results were truncated is still a
    # partial census, and the difference has to survive to the reader.
    with app.app_context():
        corpus()
        with db.session_scope() as session:
            session.add(
                UserScriptCensusState(
                    wiki=FRWIKI,
                    sweeps_completed=1,
                    last_started_at=utcnow(),
                    last_success_at=utcnow(),
                    enumeration_complete=False,
                )
            )
    disclosed = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}").get_json()["coverage"]
    assert disclosed["enumerated"] is False
    assert disclosed["sweptAt"].endswith("Z")


def test_one_script_lists_the_pages_filed_under_it(app, client):
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/script/?wiki={FRWIKI}&title=User:Aaa/popular.js").get_json()
    assert body["demand"] == 2
    assert body["instances"] == 2
    # Byte-identical is a fact and a shared name is an inference; a reviewer
    # has to be able to tell which filed each page.
    with app.app_context():
        members = [
            {"id": identity(title), "title": title, "relation": projection.RELATION_COPY}
            for title in ("User:Bbb/popular.js", "User:Ccc/popular.js")
        ]
    assert body["members"] == members


def test_one_script_requires_an_identity_or_a_wiki_and_title(client):
    assert client.get("/v1/userscripts/script/").status_code == 400
    assert client.get(f"/v1/userscripts/script/?wiki={FRWIKI}").status_code == 400


def test_a_folded_page_is_told_where_it_went(app, client):
    with app.app_context():
        corpus()
        origin = identity("User:Aaa/popular.js")
    resp = client.get(f"/v1/userscripts/script/?wiki={FRWIKI}&title=User:Bbb/popular.js")
    assert resp.status_code == 404
    assert resp.get_json() == {
        "error": "not an original",
        "filedUnder": "User:Aaa/popular.js",
        "filedUnderId": origin,
    }


def test_a_script_answers_to_its_identity_as_well_as_to_its_title(app, client):
    with app.app_context():
        corpus()
        script = identity("User:Aaa/popular.js")
    by_title = client.get(f"/v1/userscripts/script/?wiki={FRWIKI}&title=User:Aaa/popular.js").get_json()
    by_id = client.get(f"/v1/userscripts/script/?id={script}").get_json()
    assert by_title["id"] == script
    assert by_id == by_title


def test_an_identity_survives_a_rebuild_that_renumbers_every_directory_row(app, client):
    # The point of disclosing the census id rather than the directory row id.
    # Projecting again deletes and re-inserts every row in both directory
    # tables, so a caller who had written down a row id would now be holding a
    # number that means something else -- or nothing.
    with app.app_context():
        corpus()
        script = identity("User:Aaa/popular.js")
        page("User:Ggg/unrelated.js", rank=4)
        projection.project(FRWIKI)
    assert client.get(f"/v1/userscripts/script/?id={script}").get_json()["title"] == "User:Aaa/popular.js"


def test_a_folded_page_answers_to_its_identity_too(app, client):
    with app.app_context():
        corpus()
        forked, origin = identity("User:Bbb/popular.js"), identity("User:Aaa/popular.js")
    resp = client.get(f"/v1/userscripts/script/?id={forked}")
    assert resp.status_code == 404
    assert resp.get_json()["filedUnderId"] == origin


def test_an_identity_nobody_has_seen_is_a_plain_404(app, client):
    with app.app_context():
        corpus()
    assert client.get("/v1/userscripts/script/?id=999999").status_code == 404


def test_a_title_nobody_has_seen_is_a_plain_404(app, client):
    with app.app_context():
        corpus()
    resp = client.get(f"/v1/userscripts/script/?wiki={FRWIKI}&title=User:Nobody/nothing.js")
    assert resp.status_code == 404
    assert "no such script" in resp.get_json()["error"]


def test_the_wiki_listing_covers_swept_and_projected_wikis_alike(app, client):
    with app.app_context():
        corpus()
        with db.session_scope() as session:
            session.add(UserScriptCensusState(wiki=ENWIKI, sweeps_completed=1))
    body = client.get("/v1/userscripts/wikis/").get_json()
    assert [row["wiki"] for row in body["results"]] == [ENWIKI, FRWIKI]
    assert body["count"] == 2


def test_every_read_endpoint_is_rate_limited(app, client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _addr: True)
    for path in (
        "/v1/userscripts/wikis/",
        f"/v1/userscripts/directory/?wiki={FRWIKI}",
        f"/v1/userscripts/script/?wiki={FRWIKI}&title=x",
    ):
        assert client.get(path).status_code == 429


def counted_queries():
    """Count the SELECTs one block of work issues, on the engine under test."""
    from sqlalchemy import event

    engine = db.engine()
    seen: list[str] = []

    def record(_conn, _cursor, statement, *_rest):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    return seen, lambda: event.remove(engine, "before_cursor_execute", record)


def swept(wiki, *, sweeps=1):
    """A wiki the census has touched, with one page and one directory entry."""
    page("User:Aaa/only.js", wiki=wiki)
    with db.session_scope() as session:
        session.add(UserScriptCensusState(wiki=wiki, sweeps_completed=sweeps))
    projection.project(wiki)


def test_the_wiki_listing_costs_the_same_number_of_queries_at_any_roster_size(app, client):
    """The listing must not read per wiki.

    It used to call `coverage()` once per wiki -- four queries each, one of them
    a COUNT over every stored script page. That was twelve queries while the
    census covered three wikis. Across every Wikimedia project it was four
    thousand and fourteen seconds, which is past the browser's read timeout, so
    the page that consumes this endpoint stopped rendering entirely. Correctness
    never moved, which is exactly why only a cost assertion catches it.
    """
    with app.app_context():
        for index in range(3):
            swept(f"w{index}.wikipedia.org")
        seen, stop = counted_queries()
        try:
            small = client.get("/v1/userscripts/wikis/").get_json()
            few = len(seen)
            seen.clear()
            for index in range(3, 30):
                swept(f"w{index}.wikipedia.org")
            seen.clear()
            large = client.get("/v1/userscripts/wikis/").get_json()
            many = len(seen)
        finally:
            stop()
    assert small["count"] == 3
    assert large["count"] == 30
    # Ten times the wikis, the same reads. The absolute number is not the point
    # and is left loose; that it does not grow with the roster is the point.
    assert many == few
    assert few <= 6


def test_the_wiki_listing_keeps_each_wikis_numbers_with_its_own_wiki(app, client):
    """Grouped reads must not smear one wiki's counts across another.

    Four separate grouped queries are stitched back together in Python, so the
    failure this guards against is a join by position rather than by wiki --
    which a single-wiki fixture cannot show.
    """
    with app.app_context():
        corpus()
        swept(ENWIKI, sweeps=7)
        page("User:Ggg/extra.js", wiki=ENWIKI)
        projection.project(ENWIKI)
    rows = {row["wiki"]: row for row in client.get("/v1/userscripts/wikis/").get_json()["results"]}
    assert set(rows) == {ENWIKI, FRWIKI}
    assert rows[ENWIKI]["sweepsCompleted"] == 7
    assert rows[FRWIKI]["sweepsCompleted"] == 0
    assert rows[ENWIKI]["pages"] == 2
    assert rows[FRWIKI]["pages"] == 4
    assert rows[FRWIKI]["active"] > 0


def test_the_wiki_listing_agrees_with_the_per_wiki_coverage_it_replaced(app, client):
    """The bulk reader and the one-wiki reader must describe a wiki identically."""
    with app.app_context():
        corpus()
        swept(ENWIKI, sweeps=2)
    listed = {row["wiki"]: row for row in client.get("/v1/userscripts/wikis/").get_json()["results"]}
    for wiki in (ENWIKI, FRWIKI):
        alone = client.get(f"/v1/userscripts/directory/?wiki={wiki}").get_json()["coverage"]
        assert listed[wiki] == alone
