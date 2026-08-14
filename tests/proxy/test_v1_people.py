# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_people.py: the /v1/people/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database, the same
way tests/proxy/test_v1_claims.py does, without importing from test_backend.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, security  # noqa: E402
from backend.models import Person, PersonProfile  # noqa: E402


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


def make_person(display_name, *, canonical_key=None):
    with db.session_scope() as s:
        person = Person(
            canonical_key=canonical_key or f"display:{display_name.casefold()}",
            display_name=display_name,
            identity_quality="display_name",
        )
        s.add(person)
        s.flush()
        s.add(PersonProfile(person_id=person.id, visibility="public"))
        s.flush()
        return person.public_id


# ---------------------------------------------------------------------------
# /v1/people/tools/<name>/


def test_tool_people_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _remote_addr: True)
    resp = client.get("/v1/people/tools/some-tool/")
    assert resp.status_code == 429


def test_tool_people_requires_a_non_blank_name(client):
    resp = client.get("/v1/people/tools/%20/")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "tool name is required"


# ---------------------------------------------------------------------------
# /v1/people/


def test_people_directory_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _remote_addr: True)
    resp = client.get("/v1/people/")
    assert resp.status_code == 429


def test_people_directory_rejects_an_overlong_query(client):
    resp = client.get("/v1/people/?q=" + "a" * 256)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "q must be 255 characters or fewer"


def test_people_directory_rejects_an_overlong_project(client):
    resp = client.get("/v1/people/?project=" + "a" * 256)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "project must be 255 characters or fewer"


def test_people_directory_legacy_limit_param_becomes_page_size_and_builds_next_url(client):
    for index in range(3):
        make_person(f"Directory Person {index}")
    resp = client.get("/v1/people/?limit=2")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["pageSize"] == 2
    assert body["nextPage"] == 2
    assert body["next"] is not None
    assert "page_size=2" in body["next"]
    assert "limit" not in body["next"]
    assert "page=2" in body["next"]
    assert body["previous"] is None
    assert body["source"] == "local"
    assert body["syncStatus"] == "evolved_real"
    assert body["canonicalAuthority"] == {"catalog": "toolhub", "profiles": "toolhub-evolved"}


def test_people_directory_previous_page_url_is_built_on_page_two(client):
    for index in range(3):
        make_person(f"Second Page Person {index}")
    resp = client.get("/v1/people/?page_size=2&page=2")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["previous"] is not None
    assert "page=1" in body["previous"]
    assert body["next"] is None


def test_people_directory_rejects_invalid_parameters(client):
    assert client.get("/v1/people/?page=0").status_code == 400
    assert client.get("/v1/people/?role=bogus-role").status_code == 400


# ---------------------------------------------------------------------------
# /v1/people/attributions/


def test_people_attributions_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _remote_addr: True)
    resp = client.get("/v1/people/attributions/")
    assert resp.status_code == 429


def test_people_attributions_rejects_an_overlong_query(client):
    resp = client.get("/v1/people/attributions/?q=" + "a" * 256)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "q must be 255 characters or fewer"


def test_people_attributions_rejects_an_overlong_project(client):
    resp = client.get("/v1/people/attributions/?project=" + "a" * 256)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "project must be 255 characters or fewer"


def test_people_attributions_ok_response_shape(client):
    resp = client.get("/v1/people/attributions/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "local"
    assert body["syncStatus"] == "evolved_real"
    assert body["canonicalAuthority"] == {"catalog": "toolhub", "profiles": "toolhub-evolved"}


# ---------------------------------------------------------------------------
# /v1/people/resolve/


def test_people_resolve_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _remote_addr: True)
    resp = client.get("/v1/people/resolve/?handle=someone")
    assert resp.status_code == 429


def test_people_resolve_requires_a_handle(client):
    resp = client.get("/v1/people/resolve/")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "handle is required"


def test_people_resolve_ok_response_shape(client):
    resp = client.get("/v1/people/resolve/?handle=nobody")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "not_found"
    assert body["source"] == "local"
    assert body["canonicalAuthority"] == {"catalog": "toolhub", "profiles": "toolhub-evolved"}


# ---------------------------------------------------------------------------
# /v1/people/<public_id>/


def test_person_detail_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _remote_addr: True)
    resp = client.get("/v1/people/some-id/")
    assert resp.status_code == 429


def test_person_detail_rejects_invalid_tool_page(client):
    public_id = make_person("Paged Person")
    resp = client.get(f"/v1/people/{public_id}/?tool_page=0")
    assert resp.status_code == 400


def test_person_detail_reports_not_found_for_an_unknown_person(client):
    resp = client.get("/v1/people/does-not-exist/")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "person not found"


def test_person_detail_ok_response_includes_tool_pagination_urls(client):
    public_id = make_person("Detail Person")
    resp = client.get(f"/v1/people/{public_id}/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == public_id
    assert body["tools"]["next"] is None
    assert body["tools"]["previous"] is None
