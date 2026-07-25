# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the backend package: db plumbing, security guards, OAuth, /v1 API.

Every test runs on a fresh in-memory SQLite database; OAuth's upstream calls
are monkeypatched. The suite exercises every branch (the coverage gate is
100% with branch coverage across app, backend and crawl).
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, oauth, security  # noqa: E402
from backend.models import ActivityRow, ToolRecord, User, utcnow  # noqa: E402
from backend.v1 import FEED_KEEP_CAP, _iso, _parse_iso  # noqa: E402


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


def add_user(username="Ada", wm_sub="42"):
    with db.session_scope() as s:
        user = User(wm_sub=wm_sub, username=username)
        s.add(user)
        s.flush()
        return user.id


def sign_in(client, uid, csrf="tok"):
    with client.session_transaction() as sess:
        sess["uid"] = uid
        sess["csrf"] = csrf


def put_overlay(client, key, value, csrf="tok"):
    return client.put(f"/v1/overlay/{key}", json=value, headers={"X-CSRF-Token": csrf})


# ---- register / config -----------------------------------------------------


def test_register_env_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/nested/env.sqlite3")
    monkeypatch.setenv("TOOLHUB_SECRET_KEY", "env-secret")
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    application = Flask(__name__)
    backend.register(application)
    assert application.secret_key == "env-secret"
    assert application.config["SESSION_COOKIE_SECURE"] is False
    assert (tmp_path / "nested").is_dir()


def test_register_defaults_generate_secret(monkeypatch):
    monkeypatch.delenv("TOOLHUB_SECRET_KEY", raising=False)
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    application = Flask(__name__)
    backend.register(application)
    assert len(application.secret_key) == 64  # random hex fallback
    assert application.config["SESSION_COOKIE_SECURE"] is True


# ---- db plumbing -----------------------------------------------------------


def test_db_requires_configure():
    saved_engine, saved_factory = db._engine, db._session_factory
    db._engine, db._session_factory = None, None
    try:
        with pytest.raises(RuntimeError):
            db.engine()
        with pytest.raises(RuntimeError), db.session_scope():
            pass
    finally:
        db._engine, db._session_factory = saved_engine, saved_factory


def test_db_reconfigure_disposes_and_file_url(tmp_path):
    db.configure("sqlite://")
    db.configure(f"sqlite:///{tmp_path}/file.sqlite3")  # non-memory branch + dispose branch
    db.init_schema()
    with db.session_scope() as s:
        s.add(User(wm_sub="x", username="y"))
    db.configure("sqlite://")
    db.init_schema()


def test_session_scope_rolls_back_on_error(app):
    with pytest.raises(ValueError, match="boom"), db.session_scope() as s:
        s.add(User(wm_sub="r", username="r"))
        raise ValueError("boom")
    with db.session_scope() as s:
        assert s.query(User).count() == 0


# ---- security guards -------------------------------------------------------


def test_v1_user_requires_session(client):
    resp = client.get("/v1/user/")
    assert resp.status_code == 401
    assert resp.get_json() == {"authenticated": False}


def test_v1_user_stale_uid_clears_session(client):
    sign_in(client, 999)
    resp = client.get("/v1/user/")
    assert resp.status_code == 401


def test_v1_user_ok(client):
    uid = add_user()
    sign_in(client, uid)
    data = client.get("/v1/user/").get_json()
    assert data == {"authenticated": True, "username": "Ada", "csrf": "tok"}


def test_overlay_get_requires_login(client):
    assert client.get("/v1/overlay/").status_code == 401


def test_put_requires_login(client):
    assert client.put("/v1/overlay/favorites", json=[]).status_code == 401


def test_put_requires_csrf(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.put("/v1/overlay/favorites", json=[]).status_code == 403  # missing header
    assert put_overlay(client, "favorites", [], csrf="wrong").status_code == 403  # mismatch


def test_rate_limit(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    for _ in range(security.WRITE_LIMIT):
        assert put_overlay(client, "favorites", ["a"]).status_code == 200
    assert put_overlay(client, "favorites", ["a"]).status_code == 429
    clock["t"] += security.WRITE_WINDOW_SECONDS + 1  # window expires → pruning branch
    assert put_overlay(client, "favorites", ["a"]).status_code == 200


# ---- overlay round-trips ---------------------------------------------------


def test_overlay_roundtrip_all_keys(client):
    uid = add_user()
    sign_in(client, uid)
    assert put_overlay(client, "favorites", ["tool-b", "tool-a", "tool-b"]).status_code == 200  # dupe dropped
    lists = [{"id": "demo-1", "title": "My list", "description": "d", "tools": ["tool-a"], "modified": "2026-07-25T10:00:00Z"}]
    assert put_overlay(client, "lists", lists).status_code == 200
    assert put_overlay(client, "crawlerUrls", [{"url": "https://example.org/t.json", "added": "bogus-date"}]).status_code == 200
    assert put_overlay(client, "toolEdits", {"tool-a": {"title": "New"}}).status_code == 200
    assert put_overlay(client, "toolAnnos", {"tool-a": {"audiences": ["editors"]}}).status_code == 200
    assert put_overlay(client, "toolNew", {"my-tool": {"title": "T", "url": "https://example.org"}}).status_code == 200
    revs = [{"id": "d1", "timestamp": "2026-07-25T10:00:00Z", "comment": "Demo: edited"}]
    assert put_overlay(client, "revisions", revs).status_code == 200
    assert put_overlay(client, "revisions", revs).status_code == 200  # idempotent (known id skipped)
    assert put_overlay(client, "auditlogs", [{"id": "d1", "action": "edited"}]).status_code == 200

    data = client.get("/v1/overlay/").get_json()
    assert data["favorites"] == ["tool-b", "tool-a"]
    assert data["lists"][0]["id"] == "demo-1"
    assert data["lists"][0]["modified"] == "2026-07-25T10:00:00Z"
    assert data["crawlerUrls"][0]["url"] == "https://example.org/t.json"
    assert data["toolEdits"] == {"tool-a": {"title": "New"}}
    assert data["toolAnnos"] == {"tool-a": {"audiences": ["editors"]}}
    assert data["toolNew"]["my-tool"]["title"] == "T"
    assert data["revisions"] == revs
    assert data["auditlogs"][0]["action"] == "edited"


def test_overlay_replace_semantics_and_merge(client):
    uid_a = add_user("Ada", "1")
    uid_b = add_user("Grace", "2")
    sign_in(client, uid_a)
    put_overlay(client, "favorites", ["one"])
    put_overlay(client, "favorites", ["two"])  # replaces, not appends
    put_overlay(client, "toolEdits", {"t": {"title": "from-ada"}})
    data = client.get("/v1/overlay/").get_json()
    assert data["favorites"] == ["two"]
    sign_in(client, uid_b)
    put_overlay(client, "toolEdits", {"t": {"title": "from-grace"}})
    data = client.get("/v1/overlay/").get_json()
    assert data["favorites"] == []  # per-user
    assert data["toolEdits"]["t"]["title"] == "from-grace"  # global merge, newest wins


def test_put_validation_errors(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.put("/v1/overlay/favorites", data="not json", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 400  # non-JSON body
    assert put_overlay(client, "favorites", "nope").status_code == 400
    assert put_overlay(client, "favorites", [""]).status_code == 400
    assert put_overlay(client, "lists", "nope").status_code == 400
    assert put_overlay(client, "lists", [{"id": 5}]).status_code == 400
    assert put_overlay(client, "crawlerUrls", [{"url": "http://insecure"}]).status_code == 400
    assert put_overlay(client, "toolEdits", {"t": "not-an-object"}).status_code == 400
    assert put_overlay(client, "toolNew", []).status_code == 400
    assert put_overlay(client, "revisions", [{"no-id": True}]).status_code == 400
    assert put_overlay(client, "unknown-key", []).status_code == 404


def test_feed_trim(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        for i in range(FEED_KEEP_CAP):
            s.add(ActivityRow(kind="revisions", client_id=f"old{i}", user_id=uid, row={"id": f"old{i}"}, created_at=utcnow()))
    assert put_overlay(client, "revisions", [{"id": "brand-new"}]).status_code == 200
    with db.session_scope() as s:
        assert s.query(ActivityRow).filter(ActivityRow.kind == "revisions").count() == FEED_KEEP_CAP


# ---- iso helpers -----------------------------------------------------------


def test_iso_helpers():
    assert _iso(None) == ""
    assert _iso(utcnow()).endswith("Z")
    assert _parse_iso("2026-07-25T10:00:00+02:00").hour == 8  # aware → UTC naive
    assert _parse_iso("2026-07-25T10:00:00").hour == 10  # naive kept
    assert _parse_iso(None).year >= 2026  # invalid → now


# ---- public endpoints ------------------------------------------------------


def test_healthz_ok_and_failure(client):
    assert client.get("/healthz").get_json() == {"ok": True}
    db.configure("sqlite:////nonexistent-dir/x/y.sqlite3")  # unreachable db
    assert client.get("/healthz").status_code == 503
    db.configure("sqlite://")
    db.init_schema()


def test_search_and_toolinfo_feed(client):
    uid = add_user()
    with db.session_scope() as s:
        s.add(ToolRecord(tool_name="alpha", user_id=uid, record={"title": "Alpha", "description": "First", "url": "https://a.example", "keywords": ["cite"]}, modified_at=utcnow()))
        s.add(ToolRecord(tool_name="beta", user_id=uid, record={"title": "Beta", "description": "Second"}, modified_at=utcnow()))
    all_results = client.get("/v1/search/tools/").get_json()
    assert all_results["count"] == 2  # empty q matches everything
    assert client.get("/v1/search/tools/?q=alp").get_json()["count"] == 1  # by name
    assert client.get("/v1/search/tools/?q=first").get_json()["count"] == 1  # by description
    assert client.get("/v1/search/tools/?q=cite").get_json()["count"] == 1  # by keyword
    assert client.get("/v1/search/tools/?q=zzz").get_json()["count"] == 0
    feed = client.get("/toolinfo.json").get_json()
    assert len(feed) == 1  # beta has no https url → excluded
    assert feed[0]["name"] == "toolhub-evolved-alpha"
    assert feed[0]["keywords"] == "cite"


# ---- oauth -----------------------------------------------------------------


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise oauth.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def configure_oauth(monkeypatch):
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_SECRET", "csec")


def test_v1_config_reports_oauth(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    assert client.get("/v1/config/").get_json() == {"oauth": False}
    configure_oauth(monkeypatch)
    assert client.get("/v1/config/").get_json() == {"oauth": True}


def test_oauth_login_unconfigured(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    assert client.get("/oauth/login").status_code == 503


def test_oauth_login_redirects(client, monkeypatch):
    configure_oauth(monkeypatch)
    resp = client.get("/oauth/login")
    assert resp.status_code == 302
    assert "oauth2/authorize" in resp.headers["Location"]
    assert "client_id=cid" in resp.headers["Location"]


def test_oauth_callback_rejects_bad_state(client, monkeypatch):
    configure_oauth(monkeypatch)
    resp = client.get("/oauth/callback?code=c&state=unknown")  # no stored state
    assert resp.headers["Location"] == "/?login=error"
    client.get("/oauth/login")
    resp = client.get("/oauth/callback?code=c&state=wrong")  # mismatch
    assert resp.headers["Location"] == "/?login=error"
    client.get("/oauth/login")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    resp = client.get(f"/oauth/callback?state={state}")  # missing code
    assert resp.headers["Location"] == "/?login=error"


def test_oauth_callback_unconfigured(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    with client.session_transaction() as sess:
        sess["oauth_state"] = "s"
    assert client.get("/oauth/callback?code=c&state=s").headers["Location"] == "/?login=error"


def start_login(client):
    client.get("/oauth/login")
    with client.session_transaction() as sess:
        return sess["oauth_state"]


def test_oauth_callback_upstream_failure(client, monkeypatch):
    configure_oauth(monkeypatch)
    state = start_login(client)
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **k: (_ for _ in ()).throw(oauth.requests.RequestException("down")))
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def test_oauth_callback_bad_profile(client, monkeypatch):
    configure_oauth(monkeypatch)
    state = start_login(client)
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(oauth.requests, "get", lambda *a, **k: FakeResp({"unexpected": True}))
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def test_oauth_callback_success_and_relogin(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(oauth.requests, "get", lambda *a, **k: FakeResp({"sub": 7, "username": "Ada"}))
    state = start_login(client)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/"
    me = client.get("/v1/user/").get_json()
    assert me["authenticated"] is True
    assert me["username"] == "Ada"
    assert me["csrf"]
    # second login for the same wm_sub updates the username instead of duplicating
    monkeypatch.setattr(oauth.requests, "get", lambda *a, **k: FakeResp({"sub": 7, "username": "Ada Renamed"}))
    state = start_login(client)
    client.get(f"/oauth/callback?code=c&state={state}")
    assert client.get("/v1/user/").get_json()["username"] == "Ada Renamed"
    with db.session_scope() as s:
        assert s.query(User).count() == 1


def test_oauth_logout(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/oauth/logout")
    assert resp.headers["Location"] == "/"
    assert client.get("/v1/user/").status_code == 401
