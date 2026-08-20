# SPDX-License-Identifier: GPL-3.0-or-later
"""Read endpoints over a wiki's user-script directory: listing, one script, coverage."""

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
                owner=directory.owner_of(title),
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


def corpus():
    """A small frwiki: one popular script with a fork, one nobody loads."""
    page("User:Aaa/popular.js", rank=0, fingerprint="copy")
    page("User:Bbb/popular.js", rank=1, fingerprint="copy")
    page("User:Ccc/popular.js", rank=2, fingerprint="copy")
    page("User:Ddd/quiet.js", rank=3)
    for who in ["Eee", "Fff"]:
        loads(f"User:{who}/common.js", "User:Aaa/popular.js")
    projection.project(FRWIKI)


def test_listing_requires_a_wiki(client):
    assert client.get("/v1/userscripts/directory/").status_code == 400


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
        "computedAt": "",
        "active": 0,
        "archive": 0,
    }


def test_coverage_reports_the_sweep_behind_the_directory(app, client):
    with app.app_context():
        corpus()
        with db.session_scope() as session:
            session.add(UserScriptCensusState(wiki=FRWIKI, sweeps_completed=2, last_success_at=utcnow()))
    disclosed = client.get(f"/v1/userscripts/directory/?wiki={FRWIKI}").get_json()["coverage"]
    assert disclosed["sweepsCompleted"] == 2
    assert disclosed["sweptAt"].endswith("Z")
    assert disclosed["computedAt"].endswith("Z")
    assert (disclosed["pages"], disclosed["active"], disclosed["archive"]) == (4, 1, 1)


def test_one_script_lists_the_pages_filed_under_it(app, client):
    with app.app_context():
        corpus()
    body = client.get(f"/v1/userscripts/script/?wiki={FRWIKI}&title=User:Aaa/popular.js").get_json()
    assert body["demand"] == 2
    assert body["instances"] == 2
    # Byte-identical is a fact and a shared name is an inference; a reviewer
    # has to be able to tell which filed each page.
    assert body["members"] == [
        {"title": "User:Bbb/popular.js", "relation": projection.RELATION_COPY},
        {"title": "User:Ccc/popular.js", "relation": projection.RELATION_COPY},
    ]


def test_one_script_requires_both_a_wiki_and_a_title(client):
    assert client.get("/v1/userscripts/script/").status_code == 400
    assert client.get(f"/v1/userscripts/script/?wiki={FRWIKI}").status_code == 400


def test_a_folded_page_is_told_where_it_went(app, client):
    with app.app_context():
        corpus()
    resp = client.get(f"/v1/userscripts/script/?wiki={FRWIKI}&title=User:Bbb/popular.js")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "not an original", "filedUnder": "User:Aaa/popular.js"}


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
