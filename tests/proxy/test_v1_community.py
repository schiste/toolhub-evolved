# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_community.py: the /v1/community/ endpoint.

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


def test_community_search_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _remote_addr: True)
    resp = client.get("/v1/community/")
    assert resp.status_code == 429


def test_community_search_rejects_overlong_query_or_project(client):
    resp = client.get("/v1/community/?q=" + "a" * 256)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "q and project must be 255 characters or fewer"

    resp = client.get("/v1/community/?project=" + "a" * 256)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "q and project must be 255 characters or fewer"


def test_community_search_rejects_invalid_query_parameters(client):
    for path in (
        "/v1/community/?page=0",
        "/v1/community/?page_size=nope",
        "/v1/community/?ordering=alphabetical",
        "/v1/community/?contributor=registered",
    ):
        assert client.get(path).status_code == 400


def test_community_search_positive_arg_returns_the_parsed_value_without_a_maximum(client):
    for index in range(3):
        make_person(f"Community Person {index}")
    resp = client.get("/v1/community/?page=1")
    assert resp.status_code == 200


def test_community_search_builds_next_and_previous_page_urls(client):
    for index in range(3):
        make_person(f"Paged Person {index}")
    first = client.get("/v1/community/?q=Paged&page_size=2").get_json()
    assert first["nextPage"] == 2
    assert first["next"] is not None
    assert "page=2" in first["next"]
    assert first["previous"] is None

    second = client.get("/v1/community/?q=Paged&page_size=2&page=2").get_json()
    assert second["previous"] is not None
    assert "page=1" in second["previous"]
    assert second["next"] is None


def test_community_search_ok_response_shape(client):
    make_person("Shape Person")
    resp = client.get("/v1/community/?q=Shape")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "local"
    assert body["syncStatus"] == "evolved_real"
    assert body["canonicalAuthority"] == {
        "accounts": "toolhub",
        "catalog": "toolhub",
        "profiles": "toolhub-evolved",
    }
