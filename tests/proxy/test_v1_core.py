# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1.py: feeds, config, issue reports, home.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it.

Pure helper functions (_feed_text, _feed_payload) are called directly since
they don't touch Flask request state or the database; the route-level
branches (feed exception handling, name validation, issue-report validation)
are driven through the test client.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.orm import Session as OrmSession

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
from backend import authz, db, github_issues, security  # noqa: E402
from backend.models import IssueReport, User  # noqa: E402


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


def add_user(username="Ada", wm_sub="42", role=authz.ROLE_USER):
    with db.session_scope() as s:
        user = User(wm_sub=wm_sub, username=username, role=role)
        s.add(user)
        s.flush()
        return user.id


def sign_in(client, uid, csrf="tok"):
    with db.session_scope() as s:
        user = s.get(User, uid)
        epoch = user.session_epoch or 0 if user is not None else 0
    with client.session_transaction() as sess:
        sess["uid"] = uid
        sess["csrf"] = csrf
        sess["epoch"] = epoch


# ---------------------------------------------------------------------------
# _public_base_url


def test_public_base_url_dev_falls_back_to_request_host(app, monkeypatch):
    monkeypatch.delenv("TOOLHUB_EVOLVED_BASE_URL", raising=False)
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    with app.test_request_context("/", base_url="http://localhost:5000"):
        assert v1_api._public_base_url() == "http://localhost:5000"


# ---------------------------------------------------------------------------
# _feed_text (pure helper, called directly)


def test_feed_text_dict_falls_back_through_other_keys():
    # "en"/"mul" absent -> loops back (156->158 false, 158->156), then finds
    # a truthy value among the remaining dict values.
    assert v1_api._feed_text({"fr": "Bonjour"}) == "Bonjour"


def test_feed_text_dict_all_falsy_returns_fallback():
    assert v1_api._feed_text({"en": "", "mul": None, "fr": ""}, "fallback") == "fallback"


def test_feed_text_dict_prefers_en_then_mul():
    assert v1_api._feed_text({"en": "Hello"}) == "Hello"
    assert v1_api._feed_text({"en": "", "mul": "Hola"}) == "Hola"


def test_feed_text_list():
    assert v1_api._feed_text(["a", "", "b"]) == "a, b"
    assert v1_api._feed_text([], "none") == "none"


def test_feed_text_scalar():
    assert v1_api._feed_text(None, "empty") == "empty"
    assert v1_api._feed_text("  x  ") == "x"


# ---------------------------------------------------------------------------
# _feed_payload (pure-ish helper; reads the local catalog boundary)


def test_feed_payload_non_dict_returns_empty_list(monkeypatch):
    monkeypatch.setattr(v1_api.catalog_read, "collection_payload", lambda path, params=None: None)
    assert v1_api._feed_payload("/api/recent/") == []


# ---------------------------------------------------------------------------
# feed routes: upstream failure -> 502, and name-required validation


def test_feed_recently_updated_tools_upstream_failure(client, monkeypatch):
    def boom(params=None):
        raise RuntimeError("local catalog unavailable")

    monkeypatch.setattr(v1_api.catalog_read, "search_payload", boom)
    resp = client.get("/feeds/tools/recently-updated.xml")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "feed upstream unavailable"


def test_feed_recently_updated_tools_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        v1_api.catalog_read,
        "search_payload",
        lambda params=None: {"results": [{"name": "alpha", "title": "Alpha"}]},
    )
    resp = client.get("/feeds/tools/recently-updated.xml")
    assert resp.status_code == 200
    assert b"Alpha" in resp.data


def test_feed_lists_upstream_failure(client, monkeypatch):
    def boom(path, params=None):
        raise RuntimeError("local catalog unavailable")

    monkeypatch.setattr(v1_api.catalog_read, "collection_payload", boom)
    resp = client.get("/feeds/lists.xml")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "feed upstream unavailable"


def test_feed_lists_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        v1_api.catalog_read,
        "collection_payload",
        lambda path, params=None: {"results": [{"id": "1", "title": "A list"}]},
    )
    resp = client.get("/feeds/lists.xml")
    assert resp.status_code == 200
    assert b"A list" in resp.data


def test_feed_tool_revisions_blank_name_is_rejected(client):
    resp = client.get("/feeds/tools/%20/revisions.xml")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "tool name is required"


def test_feed_tool_revisions_upstream_failure(client, monkeypatch):
    def boom(url):
        raise RuntimeError("local catalog unavailable")

    monkeypatch.setattr(v1_api.catalog_read, "cached_payload", boom)
    resp = client.get("/feeds/tools/alpha-tool/revisions.xml")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "feed upstream unavailable"


def test_feed_tool_revisions_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        v1_api.catalog_read,
        "cached_payload",
        lambda url: (b'{"results":[{"id":"r1","user":{"username":"Ada"}}]}', "application/json", 200),
    )
    resp = client.get("/feeds/tools/alpha-tool/revisions.xml")
    assert resp.status_code == 200
    assert b"alpha-tool" in resp.data


def test_feed_list_revisions_blank_id_is_rejected(client):
    resp = client.get("/feeds/lists/%20/revisions.xml")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "list id is required"


def test_feed_list_revisions_upstream_failure(client, monkeypatch):
    def boom(url):
        raise RuntimeError("local catalog unavailable")

    monkeypatch.setattr(v1_api.catalog_read, "cached_payload", boom)
    resp = client.get("/feeds/lists/list-1/revisions.xml")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "feed upstream unavailable"


def test_feed_list_revisions_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        v1_api.catalog_read,
        "cached_payload",
        lambda url: (b'{"results":[{"id":"r1","user":{"username":"Ada"}}]}', "application/json", 200),
    )
    resp = client.get("/feeds/lists/list-1/revisions.xml")
    assert resp.status_code == 200
    assert b"list-1" in resp.data


# ---------------------------------------------------------------------------
# v1_home


def test_v1_home_endpoint(client, monkeypatch):
    monkeypatch.setattr(v1_api.home_payload, "payload", lambda summaries_for: {"ok": True})
    resp = client.get("/v1/home/")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ---------------------------------------------------------------------------
# v1_issue_report


def issue_report(client, payload):
    return client.post("/v1/issue-reports/", json=payload, headers={"X-CSRF-Token": "tok"})


def base_report_payload(**overrides):
    payload = {
        "approved": True,
        "clientId": "a" * 16,
        "title": "Something is broken",
        "description": "Steps to reproduce the bug in detail.",
        "context": {"page": "/tools/alpha"},
    }
    payload.update(overrides)
    return payload


def test_issue_report_invalid_client_id(client):
    uid = add_user()
    sign_in(client, uid)
    resp = issue_report(client, base_report_payload(clientId="too-short"))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid issue report id"


def test_issue_report_bad_title(client):
    uid = add_user()
    sign_in(client, uid)
    resp = issue_report(client, base_report_payload(title=""))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "issue title must be between 1 and 200 characters"


def test_issue_report_bad_description(client):
    uid = add_user()
    sign_in(client, uid)
    resp = issue_report(client, base_report_payload(description=""))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "issue description is required and must be at most 12000 characters"


def test_issue_report_bad_context_type(client):
    uid = add_user()
    sign_in(client, uid)
    resp = issue_report(client, base_report_payload(context=["not", "an", "object"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "issue context must be an object"


def test_issue_report_context_not_json_serializable(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    orig_dumps = v1_api.json.dumps

    def fake_dumps(obj, *args, **kwargs):
        # Only the context-size check calls json.dumps with ensure_ascii=False;
        # Flask's own jsonify (used to build the 400 response) must keep working.
        if kwargs.get("ensure_ascii") is False:
            message = "not serializable"
            raise TypeError(message)
        return orig_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(v1_api.json, "dumps", fake_dumps)
    resp = issue_report(client, base_report_payload())
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "issue context is not valid JSON"


def test_issue_report_context_too_large(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(v1_api.github_issues, "MAX_CONTEXT_CHARS", 5)
    resp = issue_report(client, base_report_payload())
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "issue context is too large"


def test_issue_report_conflict_when_client_id_belongs_to_another_user(client):
    uid_a = add_user("Ada", "42")
    uid_b = add_user("Bob", "43")
    with db.session_scope() as s:
        s.add(
            IssueReport(
                client_id="b" * 16,
                user_id=uid_b,
                title="Existing",
                repository="schiste/toolhub-evolved",
                issue_number=1,
                issue_url="https://github.com/schiste/toolhub-evolved/issues/1",
            )
        )
    sign_in(client, uid_a)
    resp = issue_report(client, base_report_payload(clientId="b" * 16))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "issue report id already belongs to another user"


def test_issue_report_returns_existing_when_same_user_retries(client):
    uid = add_user()
    with db.session_scope() as s:
        s.add(
            IssueReport(
                client_id="c" * 16,
                user_id=uid,
                title="Existing",
                repository="schiste/toolhub-evolved",
                issue_number=7,
                issue_url="https://github.com/schiste/toolhub-evolved/issues/7",
            )
        )
    sign_in(client, uid)
    resp = issue_report(client, base_report_payload(clientId="c" * 16))
    assert resp.status_code == 200
    assert resp.get_json()["number"] == 7


def test_issue_report_user_vanishes_mid_request(client, monkeypatch):
    """The re-fetch of the signed-in user inside the write session finds it gone.

    write_guard's own epoch check performs the first real Session.get(User,
    uid) lookup (cached per-request); this lets that one through and returns
    None for the view's own later lookup, simulating a delete-mid-request race.
    """
    uid = add_user()
    sign_in(client, uid)
    orig_get = OrmSession.get
    calls = {"n": 0}

    def fake_get(self, entity, ident=None, *args, **kwargs):
        if entity is User and ident == uid:
            calls["n"] += 1
            if calls["n"] > 1:
                return None
        return orig_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "get", fake_get)
    resp = issue_report(client, base_report_payload(clientId="f" * 16))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "signed-in user not found"


def test_issue_report_publishes_successfully(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(
        v1_api.github_issues,
        "publish_issue",
        lambda title, body: {
            "repository": "schiste/toolhub-evolved",
            "number": 99,
            "url": "https://github.com/schiste/toolhub-evolved/issues/99",
        },
    )
    resp = issue_report(client, base_report_payload(clientId="d" * 16))
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["number"] == 99
    with db.session_scope() as s:
        row = s.get(IssueReport, "d" * 16)
        assert row is not None
        assert row.user_id == uid


def test_issue_report_publish_error_is_reported_as_bad_gateway(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)

    def boom(title, body):
        raise github_issues.IssueUnreachableError

    monkeypatch.setattr(v1_api.github_issues, "publish_issue", boom)
    resp = issue_report(client, base_report_payload(clientId="e" * 16))
    assert resp.status_code == 502
