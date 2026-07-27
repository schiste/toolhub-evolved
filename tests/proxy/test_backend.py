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
from sqlalchemy import inspect, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import authz, db, security, sync, toolhub  # noqa: E402
from backend.models import (
    ActivityRow,
    CrawlerRun,
    CrawlerUrl,
    ToolEvent,
    ToolHealthTarget,
    ToolList,
    ToolMedia,
    ToolThanks,
    ToolhubToken,
    ToolOverlay,
    ToolRecord,
    User,
    utcnow,
)  # noqa: E402
from backend.v1 import FEED_KEEP_CAP, _iso, _merged_maps, _parse_iso, _parse_optional_iso  # noqa: E402


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


def test_schema_upgrade_and_sync_cleaners_cover_legacy_metadata():
    db.configure("sqlite://")
    eng = db.engine()
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE favorites (id INTEGER PRIMARY KEY)")
    db._upgrade_schema()
    user_columns = {col["name"] for col in inspect(eng).get_columns("users")}
    assert "role" in user_columns
    columns = {col["name"] for col in inspect(eng).get_columns("favorites")}
    assert {"source", "sync_status", "last_synced_at", "last_error"}.issubset(columns)

    assert sync.clean_source("official") == "official"
    assert sync.clean_source("bogus") == "local"
    assert sync.clean_sync_status("sync_error") == "sync_error"
    assert sync.clean_sync_status("bogus") == "local_draft"
    assert sync.clean_error(None) is None
    assert sync.clean_error("  upstream refused  ") == "upstream refused"
    assert sync.clean_error("   ") is None
    assert sync.clean_int(None) is None
    assert sync.clean_int("") is None
    assert sync.clean_int("42") == 42
    assert sync.clean_int(object()) is None

    db.configure("sqlite://")
    db.init_schema()


# ---- Evolved-local authorization ------------------------------------------


def test_authz_role_cleaning_permissions_and_labels():
    assert authz.clean_role("reviewer") == authz.ROLE_REVIEWER
    assert authz.clean_role("bogus") == authz.ROLE_USER
    assert authz.role_label(authz.ROLE_ADMIN) == "Admin/operator"
    assert authz.role_label("bogus") == "Signed-in user"
    assert authz.ACTION_PUBLIC_REVIEW not in authz.role_permissions(authz.ROLE_USER)
    assert authz.ACTION_PUBLIC_REVIEW in authz.role_permissions(authz.ROLE_REVIEWER)
    assert authz.ACTION_OPERATOR in authz.role_permissions(authz.ROLE_ADMIN)


def test_authz_can_separates_owned_data_from_evolved_roles():
    owner = User(id=1, wm_sub="1", username="Owner", role=authz.ROLE_USER)
    admin = User(id=2, wm_sub="2", username="Admin", role=authz.ROLE_ADMIN)
    assert authz.can(None, authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=1)) is False
    assert authz.can(owner, "unknown.action") is False
    assert authz.can(owner, authz.ACTION_PRIVATE_READ) is False
    assert authz.can(owner, authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=1)) is True
    assert authz.can(admin, authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=1)) is False
    assert authz.can(admin, authz.ACTION_PUBLIC_REVIEW) is True
    assert authz.can(admin, authz.ACTION_TOOLHUB_WRITE) is True


def test_authz_accepts_orm_owner_columns():
    user = User(id=7, wm_sub="7", username="Reviewer", role=authz.ROLE_REVIEWER)
    assert authz.can(user, authz.ACTION_PRIVATE_WRITE, ToolList(user_id=7, client_id="l", title="L")) is True
    assert (
        authz.can(
            user,
            authz.ACTION_PRIVATE_DELETE,
            ToolHealthTarget(tool_name="t", target_url="https://t.example", created_by_user_id=7),
        )
        is True
    )
    assert authz.can(user, authz.ACTION_PRIVATE_WRITE, object()) is False


def test_authz_login_role_from_env(monkeypatch):
    monkeypatch.setenv(authz.ADMIN_USERS_ENV, "42, Ada")
    monkeypatch.setenv(authz.REVIEWER_USERS_ENV, "Grace")
    assert authz.configured_login_role("42", "Someone") == authz.ROLE_ADMIN
    assert authz.configured_login_role("9", "ada") == authz.ROLE_ADMIN
    assert authz.configured_login_role("10", "Grace") == authz.ROLE_REVIEWER
    assert authz.configured_login_role("11", "Linus") == authz.ROLE_USER
    assert authz.role_for_login("11", "Linus", authz.ROLE_REVIEWER) == authz.ROLE_REVIEWER
    assert authz.role_for_login("42", "Someone", authz.ROLE_USER) == authz.ROLE_ADMIN


# ---- security guards -------------------------------------------------------


def test_v1_user_reports_anonymous_session(client):
    resp = client.get("/v1/user/")
    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": False}


def test_v1_user_stale_uid_clears_session(client):
    sign_in(client, 999)
    resp = client.get("/v1/user/")
    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": False}


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
    lists = [
        {
            "id": "demo-1",
            "title": "My list",
            "description": "d",
            "tools": ["tool-a"],
            "modified": "2026-07-25T10:00:00Z",
        }
    ]
    assert put_overlay(client, "lists", lists).status_code == 200
    crawler_urls = [{"url": "https://example.org/t.json", "added": "bogus-date"}]
    assert put_overlay(client, "crawlerUrls", crawler_urls).status_code == 200
    assert put_overlay(client, "toolEdits", {"tool-a": {"title": "New"}}).status_code == 200
    assert put_overlay(client, "toolAnnos", {"tool-a": {"audiences": ["editors"]}}).status_code == 200
    new_tool = {"title": "T", "description": "A tool", "url": "https://example.org", "keywords": ["k"]}
    assert put_overlay(client, "toolNew", {"my-tool": new_tool}).status_code == 200
    revs = [{"id": "d1", "timestamp": "2026-07-25T10:00:00Z", "comment": "Demo: edited"}]
    assert put_overlay(client, "revisions", revs).status_code == 200
    assert put_overlay(client, "revisions", revs).status_code == 200  # idempotent (known id skipped)
    assert put_overlay(client, "auditlogs", [{"id": "d1", "action": "edited"}]).status_code == 200

    data = client.get("/v1/overlay/").get_json()
    assert data["favorites"] == ["tool-b", "tool-a"]
    assert data["lists"][0]["id"] == "demo-1"
    assert data["lists"][0]["modified"] == "2026-07-25T10:00:00Z"
    assert data["lists"][0]["syncStatus"] == "local_draft"
    assert data["crawlerUrls"][0]["url"] == "https://example.org/t.json"
    assert data["crawlerUrls"][0]["syncStatus"] == "local_draft"
    assert data["toolEdits"]["tool-a"]["title"] == "New"
    assert data["toolEdits"]["tool-a"]["syncStatus"] == "local_draft"
    assert data["toolAnnos"]["tool-a"]["audiences"] == ["editors"]
    assert data["toolAnnos"]["tool-a"]["syncStatus"] == "local_draft"
    assert data["toolNew"]["my-tool"]["title"] == "T"
    assert data["toolNew"]["my-tool"]["visibility"] == "private"
    assert data["revisions"] == revs
    assert data["auditlogs"][0]["action"] == "edited"


def test_overlay_sync_metadata_roundtrip_and_public_crawler_records(client):
    uid = add_user()
    sign_in(client, uid)
    assert (
        put_overlay(
            client,
            "lists",
            [
                {
                    "id": "official-list",
                    "title": "Official list",
                    "description": "from Toolhub",
                    "tools": ["crawler-tool"],
                    "modified": "2026-07-26T10:00:00Z",
                    "officialId": "77",
                    "syncStatus": "official",
                    "lastError": "  stale cache  ",
                }
            ],
        ).status_code
        == 200
    )
    assert (
        put_overlay(
            client,
            "crawlerUrls",
            [
                {
                    "url": "https://example.org/toolinfo.json",
                    "added": "2026-07-26T11:00:00Z",
                    "id": "88",
                    "syncStatus": "official",
                }
            ],
        ).status_code
        == 200
    )
    assert (
        put_overlay(
            client,
            "toolEdits",
            {
                "crawler-tool": {
                    "title": "Overlay title",
                    "baseRevision": "rev-1",
                    "fieldStatuses": {"title": "accepted"},
                    "reviewStatus": "reviewed",
                    "lastError": "needs merge",
                }
            },
        ).status_code
        == 200
    )
    assert (
        put_overlay(
            client,
            "toolNew",
            {
                "crawler-tool": {
                    "title": "Crawler Tool",
                    "description": "Public via crawler origin",
                    "url": "https://crawler.example",
                    "origin": "crawler",
                    "officialName": "crawler-tool-official",
                    "toolhubResponse": {"id": 99},
                    "validationErrors": [{"field": "url"}],
                    "lastError": "local warning",
                }
            },
        ).status_code
        == 200
    )
    data = client.get("/v1/overlay/").get_json()
    assert data["lists"][0]["officialId"] == 77
    assert data["lists"][0]["lastSyncedAt"] == "2026-07-26T10:00:00Z"
    assert data["lists"][0]["lastError"] == "stale cache"
    assert data["crawlerUrls"][0]["officialId"] == 88
    assert data["crawlerUrls"][0]["id"] == 88
    assert data["crawlerUrls"][0]["lastSyncedAt"] == "2026-07-26T11:00:00Z"
    assert data["toolEdits"]["crawler-tool"]["baseRevision"] == "rev-1"
    assert data["toolEdits"]["crawler-tool"]["fieldStatuses"] == {"title": "accepted"}
    assert data["toolEdits"]["crawler-tool"]["reviewStatus"] == "reviewed"
    assert data["toolNew"]["crawler-tool"]["officialName"] == "crawler-tool-official"
    assert data["toolNew"]["crawler-tool"]["toolhubResponse"] == {"id": 99}
    assert data["toolNew"]["crawler-tool"]["validationErrors"] == [{"field": "url"}]
    assert client.get("/v1/search/tools/?q=crawler").get_json()["count"] == 1
    assert client.get("/toolinfo.json").get_json()[0]["name"] == "toolhub-evolved-crawler-tool"


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
    # record validation: a broken record must never reach the public feed/search
    assert put_overlay(client, "toolNew", {"bad": {"url": None, "keywords": None}}).status_code == 400
    bad_record = {"bad": {"title": "T", "description": "d", "url": "http://x"}}
    assert put_overlay(client, "toolNew", bad_record).status_code == 400
    assert put_overlay(client, "revisions", [{"no-id": True}]).status_code == 400
    assert put_overlay(client, "unknown-key", []).status_code == 404


TOOL_A = {"title": "Ada's tool", "description": "d", "url": "https://a.example"}


def test_pushed_echoes_never_reowned(client):
    """The pulled cache is globally merged; pushing it back must not re-own
    other users' records (Codex P1 finding on serversync write-through)."""
    uid_a = add_user("Ada", "1")
    uid_b = add_user("Grace", "2")
    sign_in(client, uid_a)
    assert put_overlay(client, "toolNew", {"adas-tool": TOOL_A}).status_code == 200
    assert put_overlay(client, "toolEdits", {"x": {"title": "ada-edit"}}).status_code == 200
    assert put_overlay(client, "revisions", [{"id": "r1", "comment": "ada"}]).status_code == 200
    # B pulls the merged overlay, adds their own tool, and echoes Ada's toolNew
    # row back; the server must skip the foreign toolNew row instead of re-owning it.
    sign_in(client, uid_b)
    pulled = client.get("/v1/overlay/").get_json()
    tool_b = {"title": "Grace's tool", "description": "d", "url": "https://g.example"}
    assert (
        put_overlay(client, "toolNew", {**pulled["toolNew"], "adas-tool": TOOL_A, "graces-tool": tool_b}).status_code
        == 200
    )
    assert put_overlay(client, "toolEdits", pulled["toolEdits"]).status_code == 200  # pure echo
    assert put_overlay(client, "revisions", [*pulled["revisions"], {"id": "r2", "comment": "grace"}]).status_code == 200
    with db.session_scope() as s:
        ada_tool = s.execute(select(ToolRecord).where(ToolRecord.tool_name == "adas-tool")).scalar_one()
        assert ada_tool.user_id == uid_a  # still Ada's — no copy under Grace
        assert s.query(ToolRecord).count() == 2
        assert s.query(ToolOverlay).count() == 1  # echoed edit not duplicated
        assert s.query(ActivityRow).filter(ActivityRow.kind == "revisions").count() == 2  # r1 not re-inserted
    # B genuinely changing an overlay entry makes it B's own contribution
    sign_in(client, uid_b)
    assert put_overlay(client, "toolEdits", {"x": {"title": "grace-edit"}}).status_code == 200
    with db.session_scope() as s:
        assert {(o.user_id, o.patch["title"]) for o in s.query(ToolOverlay)} == {
            (uid_a, "ada-edit"),
            (uid_b, "grace-edit"),
        }


def test_feed_trim(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        for i in range(FEED_KEEP_CAP):
            s.add(
                ActivityRow(
                    kind="revisions",
                    client_id=f"old{i}",
                    user_id=uid,
                    row={"id": f"old{i}"},
                    created_at=utcnow(),
                )
            )
    assert put_overlay(client, "revisions", [{"id": "brand-new"}]).status_code == 200
    with db.session_scope() as s:
        assert s.query(ActivityRow).filter(ActivityRow.kind == "revisions").count() == FEED_KEEP_CAP


def test_crawler_runs_and_user_data_controls(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(CrawlerRun(urls_count=2, added=1, updated=1, ok=False, errors=["bad url"], sync_status="sync_error"))
    runs = client.get("/v1/crawler/runs/").get_json()
    assert runs["count"] == 1
    assert runs["results"][0]["errors"] == ["bad url"]
    assert runs["results"][0]["syncStatus"] == "sync_error"

    assert put_overlay(client, "favorites", ["tool-a"]).status_code == 200
    assert put_overlay(client, "lists", [{"id": "demo-1", "title": "L", "tools": ["tool-a"]}]).status_code == 200
    assert put_overlay(client, "crawlerUrls", [{"url": "https://example.org/toolinfo.json"}]).status_code == 200
    exported = client.get("/v1/user/export/").get_json()
    assert exported["user"] == {"username": "Ada"}
    assert exported["overlay"]["favorites"] == ["tool-a"]
    resp = client.delete("/v1/user/evolved-data/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json()["deleted"]["favorites"] == 1
    with db.session_scope() as s:
        assert s.query(CrawlerUrl).count() == 0
        assert s.query(ToolList).count() == 0


# ---- iso helpers -----------------------------------------------------------


def test_iso_helpers():
    assert _iso(None) == ""
    assert _iso(utcnow()).endswith("Z")
    assert _parse_iso("2026-07-25T10:00:00+02:00").hour == 8  # aware → UTC naive
    assert _parse_iso("2026-07-25T10:00:00").hour == 10  # naive kept
    assert _parse_iso(None).year >= 2026  # invalid → now
    assert _parse_optional_iso("2026-07-25T10:00:00").hour == 10


def test_merged_maps_handles_legacy_rows_and_missing_review_metadata():
    overlay = ToolOverlay(tool_name="patched", kind="edits", patch={"title": "Patched"}, review_status=None)
    assert _merged_maps([overlay]) == {
        "patched": {"title": "Patched", "source": "local", "syncStatus": "local_draft", "syncLabel": "Local draft"}
    }

    class LegacyRow:
        tool_name = "legacy"
        record = {"title": "Legacy"}

    assert _merged_maps([LegacyRow()]) == {"legacy": {"title": "Legacy"}}


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
        s.add(
            ToolRecord(
                tool_name="alpha",
                user_id=uid,
                record={
                    "title": "Alpha",
                    "description": "First",
                    "url": "https://a.example",
                    "keywords": ["cite"],
                },
                modified_at=utcnow(),
                visibility="public",
                sync_status="evolved_real",
            )
        )
        s.add(
            ToolRecord(
                tool_name="beta",
                user_id=uid,
                record={"title": "Beta", "description": "Second"},
                modified_at=utcnow(),
                visibility="public",
                sync_status="evolved_real",
            )
        )
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


def test_real_evolved_signals_and_media(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.get("/v1/tools/alpha/signals/").get_json()["thanks"]["count"] == 0
    assert (
        client.post("/v1/tools/alpha/events/", json={"eventType": "view"}, headers={"X-CSRF-Token": "tok"}).status_code
        == 200
    )
    assert client.post("/v1/tools/alpha/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    signals = client.get("/v1/tools/alpha/signals/").get_json()
    assert signals["thanks"] == {"count": 1, "userThanked": True}
    assert signals["usage30d"]["count"] == 1
    assert client.delete("/v1/tools/alpha/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.get("/v1/tools/alpha/signals/").get_json()["thanks"]["count"] == 0

    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/healthz"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    media_payload = {"url": "https://img.example/shot.png", "license": "CC-BY-SA-4.0", "source": "Maintainer upload"}
    media = client.post("/v1/tools/alpha/media/", json=media_payload, headers={"X-CSRF-Token": "tok"})
    assert media.status_code == 200
    assert media.get_json()["media"]["reviewStatus"] == "pending"
    assert client.get("/v1/tools/alpha/media/").get_json()["count"] == 0  # pending media is not public
    with db.session_scope() as s:
        row = s.query(ToolMedia).one()
        row.review_status = "approved"
    assert client.get("/v1/tools/alpha/media/").get_json()["count"] == 1
    assert (
        client.delete(f"/v1/media/{media.get_json()['media']['id']}/", headers={"X-CSRF-Token": "tok"}).status_code
        == 200
    )
    with db.session_scope() as s:
        assert s.query(ToolEvent).count() == 1
        assert s.query(ToolThanks).count() == 1
        assert s.query(ToolHealthTarget).count() == 1
        assert s.query(ToolMedia).one().deleted_at is not None


def test_real_signal_media_validation_and_update_paths(client):
    assert client.post("/v1/tools/alpha/media/", json={"url": "https://x.example"}).status_code == 401
    uid = add_user()
    sign_in(client, uid)
    assert client.get("/v1/tools/%20/signals/").status_code == 400
    assert (
        client.post("/v1/tools/alpha/events/", json={"eventType": "bogus"}, headers={"X-CSRF-Token": "tok"}).status_code
        == 400
    )
    assert client.post("/v1/tools/%20/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "ftp://bad.example"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/first"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/second"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    with db.session_scope() as s:
        target = s.query(ToolHealthTarget).one()
        assert target.target_url == "https://alpha.example/second"
        assert target.enabled is True
        assert target.last_error is None

    assert (
        client.post(
            "/v1/tools/%20/media/",
            json={"url": "https://img.example/shot.png", "license": "CC0", "source": "test"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert client.post("/v1/tools/alpha/media/", json=[], headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert (
        client.post(
            "/v1/tools/alpha/media/",
            json={"url": "https://img.example/shot.png", "license": "", "source": "test"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert client.delete("/v1/media/999/", headers={"X-CSRF-Token": "tok"}).status_code == 404
    with db.session_scope() as s:
        other = User(wm_sub="other", username="Other")
        s.add(other)
        s.flush()
        s.add(
            ToolMedia(
                tool_name="alpha",
                user_id=other.id,
                url="https://img.example/other.png",
                license="CC0",
                source="other",
            )
        )
        s.flush()
        other_media_id = s.query(ToolMedia).filter(ToolMedia.user_id == other.id).one().id
    assert client.delete(f"/v1/media/{other_media_id}/", headers={"X-CSRF-Token": "tok"}).status_code == 404


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)
        self.ok = status < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise toolhub.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


class TextResp:
    status_code = 418
    text = "plain upstream error"
    ok = False

    def json(self):
        raise ValueError("not json")


def configure_oauth(monkeypatch):
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_SECRET", "csec")


# ---- official Toolhub client helpers ---------------------------------------


def test_toolhub_config_and_authorize_url(monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TOOLHUB_API_BASE", raising=False)
    assert toolhub.base_url() == "https://toolhub.wikimedia.org"
    assert toolhub.oauth_client() is None
    assert toolhub.configured() is False
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.authorize_url(state="s", redirect_uri="https://evolved.example/oauth/callback")
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.exchange_code(code="c", redirect_uri="https://evolved.example/oauth/callback")
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.refresh_grant("rt")

    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example/")
    url = toolhub.authorize_url(state="s", redirect_uri="https://evolved.example/oauth/callback")
    assert toolhub.base_url() == "https://toolhub.example"
    assert toolhub.oauth_client() == ("cid", "csec")
    assert "https://toolhub.example/o/authorize/?" in url
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2Fevolved.example%2Foauth%2Fcallback" in url
    assert "scope=read+write" in url
    assert "state=s" in url


def test_toolhub_current_user_rejects_bad_shapes(monkeypatch):
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"is_authenticated": False}))
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.current_user("at")
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp([]))
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.current_user("at")


def test_toolhub_text_error_payload(monkeypatch):
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: TextResp())
    with pytest.raises(toolhub.ToolhubAPIError) as exc:
        toolhub.request_with_token("POST", "/api/tools/", access_token="at", json={"name": "x"})
    assert exc.value.status_code == 418
    assert exc.value.payload == {"message": "plain upstream error"}


def test_toolhub_refreshes_expired_grant(client, monkeypatch):
    uid = add_user(wm_sub="refresh")
    configure_oauth(monkeypatch)
    toolhub.save_grant(uid, {"access_token": "old", "refresh_token": "rt", "expires_in": -120})
    calls = []
    refreshes = [
        {
            "access_token": "new",
            "refresh_token": "rt2",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "read write",
        },
        {"access_token": "new-no-rotate", "expires_in": 3600},
    ]

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return FakeResp(refreshes.pop(0))

    def fake_request(method, url, **kwargs):
        calls.append(("request", method, url, kwargs))
        return FakeResp({"ok": True})

    monkeypatch.setattr(toolhub.requests, "post", fake_post)
    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    body, status = toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    assert (body, status) == ({"ok": True}, 200)
    assert calls[0][0] == "post"
    assert calls[1][3]["headers"]["Authorization"] == "Bearer new"
    with db.session_scope() as s:
        row = s.get(ToolhubToken, uid)
        assert row.access_token == "new"
        assert row.refresh_token == "rt2"
    toolhub.save_grant(uid, {"access_token": "third"})
    with db.session_scope() as s:
        row = s.get(ToolhubToken, uid)
        assert row.access_token == "third"
        assert row.refresh_token == "rt2"
    uid_no_rotate = add_user(wm_sub="refresh-no-rotate")
    toolhub.save_grant(uid_no_rotate, {"access_token": "old2", "refresh_token": "keep", "expires_in": -120})
    toolhub.api_request(uid_no_rotate, "POST", "/api/tools/", json={"name": "x"})
    with db.session_scope() as s:
        row = s.get(ToolhubToken, uid_no_rotate)
        assert row.access_token == "new-no-rotate"
        assert row.refresh_token == "keep"


def test_toolhub_expired_grant_without_refresh_requires_reauth(client):
    uid = add_user(wm_sub="expired")
    with db.session_scope() as s:
        s.add(ToolhubToken(user_id=uid, access_token="old", expires_at=utcnow()))
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    toolhub.revoke_local_grant(uid + 1)  # no-op for missing row


# ---- official Toolhub write bridge ----------------------------------------


def test_official_write_requires_stored_toolhub_grant(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/toolhub/tools/", json={"name": "x"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 401
    assert resp.get_json()["reauth"] is True


def test_official_tool_write_forwards_with_bearer_token(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    payload = {"name": "my-tool", "title": "T", "description": "d", "url": "https://example.org"}
    resp = client.post("/v1/toolhub/tools/", json=payload, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 201
    assert resp.get_json()["toolhub"] == {"name": "my-tool"}
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://toolhub.wikimedia.org/api/tools/"
    assert calls[0][2]["headers"]["Authorization"] == "Bearer at"
    assert calls[0][2]["json"] == payload


def test_official_bridge_routes_forward_all_write_paths(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return FakeResp({"id": 99})

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    cases = [
        ("PUT", "/v1/toolhub/tools/my-tool/", {"title": "T"}, "PUT", "/api/tools/my-tool/"),
        ("DELETE", "/v1/toolhub/tools/my-tool/", None, "DELETE", "/api/tools/my-tool/"),
        ("POST", "/v1/toolhub/lists/", {"title": "L"}, "POST", "/api/lists/"),
        ("PUT", "/v1/toolhub/lists/12/", {"title": "L2"}, "PUT", "/api/lists/12/"),
        ("DELETE", "/v1/toolhub/lists/12/", None, "DELETE", "/api/lists/12/"),
        ("POST", "/v1/toolhub/user/favorites/", {"name": "my-tool"}, "POST", "/api/user/favorites/"),
        (
            "POST",
            "/v1/toolhub/crawler/urls/",
            {"url": "https://example.org/toolinfo.json"},
            "POST",
            "/api/crawler/urls/",
        ),
        ("DELETE", "/v1/toolhub/crawler/urls/9/", None, "DELETE", "/api/crawler/urls/9/"),
    ]
    for method, path, payload, _upstream_method, _upstream_path in cases:
        resp = client.open(method=method, path=path, json=payload, headers={"X-CSRF-Token": "tok"})
        assert resp.status_code == 200
    assert [(method, url.removeprefix("https://toolhub.wikimedia.org")) for method, url, _json in calls] == [
        (upstream_method, upstream_path) for *_local, upstream_method, upstream_path in cases
    ]


def test_official_json_body_must_be_object(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/toolhub/lists/", data="not json", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "body must be a JSON object"}


def test_official_annotation_failure_is_normalized(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "bad payload"}, 400))
    resp = client.put(
        "/v1/toolhub/tools/my-tool/annotations/",
        json={"tool_type": "web app"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["details"] == {"message": "bad payload"}


def test_official_write_upstream_unavailable(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})

    def fail_request(*_args, **_kwargs):
        raise toolhub.requests.ConnectionError("down")

    monkeypatch.setattr(toolhub.requests, "request", fail_request)
    resp = client.post("/v1/toolhub/tools/", json={"name": "x"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 502
    assert resp.get_json() == {"error": "official Toolhub is unavailable"}


def test_official_delete_normalizes_204(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({}, 204))
    resp = client.delete("/v1/toolhub/user/favorites/my-tool/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ---- oauth -----------------------------------------------------------------


def test_v1_config_reports_oauth(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    assert client.get("/v1/config/").get_json() == {"oauth": False, "officialWrites": False}
    configure_oauth(monkeypatch)
    assert client.get("/v1/config/").get_json() == {"oauth": True, "officialWrites": True}


def test_oauth_login_unconfigured(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    assert client.get("/oauth/login").status_code == 503


def test_oauth_login_redirects(client, monkeypatch):
    configure_oauth(monkeypatch)
    resp = client.get("/oauth/login")
    assert resp.status_code == 302
    assert "toolhub.wikimedia.org/o/authorize/" in resp.headers["Location"]
    assert "client_id=cid" in resp.headers["Location"]
    assert "scope=read+write" in resp.headers["Location"]


def test_oauth_login_uses_configured_public_base_url(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_EVOLVED_BASE_URL", "https://evolved.example")
    resp = client.get("/oauth/login")
    assert "redirect_uri=https%3A%2F%2Fevolved.example%2Foauth%2Fcallback" in resp.headers["Location"]


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

    def fail_post(*_args, **_kwargs):
        raise toolhub.requests.RequestException("down")

    monkeypatch.setattr(toolhub.requests, "post", fail_post)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def test_oauth_callback_bad_profile(client, monkeypatch):
    configure_oauth(monkeypatch)
    state = start_login(client)
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"unexpected": True}))
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def test_oauth_callback_identity_api_failure(client, monkeypatch):
    configure_oauth(monkeypatch)
    state = start_login(client)
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "denied"}, 401))
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def test_oauth_callback_success_and_relogin(client, monkeypatch):
    configure_oauth(monkeypatch)
    token_payload = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp(token_payload))
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada", "is_authenticated": True}),
    )
    state = start_login(client)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/"
    me = client.get("/v1/user/").get_json()
    assert me["authenticated"] is True
    assert me["username"] == "Ada"
    assert me["csrf"]
    with db.session_scope() as s:
        assert s.query(ToolhubToken).count() == 1
    # second login for the same Toolhub user id updates the username instead of duplicating
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada Renamed", "is_authenticated": True}),
    )
    state = start_login(client)
    client.get(f"/oauth/callback?code=c&state={state}")
    assert client.get("/v1/user/").get_json()["username"] == "Ada Renamed"
    with db.session_scope() as s:
        assert s.query(User).count() == 1


def test_oauth_logout(client):
    uid = add_user()
    toolhub.save_grant(uid, {"access_token": "at"})
    sign_in(client, uid)
    resp = client.post("/oauth/logout")
    assert resp.headers["Location"] == "/"
    assert client.get("/v1/user/").get_json() == {"authenticated": False}
    with db.session_scope() as s:
        assert s.query(ToolhubToken).count() == 0


def test_oauth_logout_without_session(client):
    resp = client.get("/oauth/logout")
    assert resp.headers["Location"] == "/"
