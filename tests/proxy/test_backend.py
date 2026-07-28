# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the backend package: db plumbing, security guards, OAuth, /v1 API.

Every test runs on a fresh in-memory SQLite database; OAuth's upstream calls
are monkeypatched. The suite exercises every branch (the coverage gate is
100% with branch coverage across app, backend and crawl).
"""

import sys
from base64 import b64encode
from collections import deque
from contextlib import contextmanager
from datetime import timedelta
from json import dumps
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
from backend import api_cache, authz, author_claims, db, recent_owners, security, sync, token_crypto, toolhub  # noqa: E402
from backend.author_claims import (  # noqa: E402
    AuthorNameProvider,
    SignedToolinfoProvider,
    ToolforgeMembershipProvider,
    ToolforgeMaintainerProvider,
    ToolhubWriteProvider,
    toolforge_tool_names_from_member_dns,
)
from backend.models import (
    ActivityRow,
    ApiCache,
    ApiCacheMeta,
    CrawlerRun,
    CrawlerUrl,
    Favorite,
    ToolEvent,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolHealthTarget,
    ToolList,
    ToolMedia,
    ToolOwnerCache,
    ToolThanks,
    ToolhubToken,
    ToolOverlay,
    ToolRecord,
    User,
    utcnow,
)  # noqa: E402
from backend.v1 import (  # noqa: E402
    FEED_KEEP_CAP,
    _invalidate_official_api_cache,
    _iso,
    _merged_maps,
    _message_from_payload,
    _official_annotation_payload,
    _official_id,
    _parse_iso,
    _parse_optional_iso,
    _string_list,
    _string_payload_value,
    _toolhub_author_names,
    _validation_errors,
)

TOOLSADMIN_MAINTAINERS_TABLE_HTML = """
<div class="cdx-table">
  <div class="cdx-table__header">
    <div class="cdx-table__header__caption" aria-hidden="true">Maintainers</div>
  </div>
  <div class="cdx-table__table-wrapper">
    <table class="cdx-table__table">
      <caption>Maintainers</caption>
      <tbody>
        <tr><td>Schiste</td></tr>
      </tbody>
    </table>
  </div>
</div>
"""


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


@pytest.fixture(autouse=True)
def _offline_toolforge_ldap(monkeypatch):
    """Keep the suite off real Wikimedia LDAP.

    ToolforgeMembershipProvider() dials ldap-ro.eqiad.wikimedia.org when ldap3 is
    installed, so any my-tools test that did not inject a lookup was making a
    live query and waiting out the connect timeout. Tests that care about
    memberships override this with their own lookup.
    """
    monkeypatch.setattr(v1_api, "TOOLFORGE_MEMBERSHIP_PROVIDER", ToolforgeMembershipProvider(lookup=lambda _u: []))


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
        sess["epoch"] = epoch  # sign-out bumps this; a stale cookie must not authenticate


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


def test_register_refuses_to_start_without_a_session_secret(monkeypatch):
    monkeypatch.delenv("TOOLHUB_SECRET_KEY", raising=False)
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    with pytest.raises(RuntimeError, match="TOOLHUB_SECRET_KEY is required"):
        backend.register(Flask(__name__))


def test_register_allows_an_ephemeral_secret_only_in_development(monkeypatch):
    monkeypatch.delenv("TOOLHUB_SECRET_KEY", raising=False)
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    application = Flask(__name__)
    backend.register(application)
    assert len(application.secret_key) == 64  # random hex fallback, dev only
    assert application.config["SESSION_COOKIE_SECURE"] is False


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


def test_init_schema_creates_persistent_api_cache_table():
    db.configure("sqlite://")
    db.init_schema()
    cols = {col["name"] for col in inspect(db.engine()).get_columns(ApiCache.__tablename__)}
    assert {
        "url_hash",
        "url",
        "status",
        "content_type",
        "body",
        "fetched_at",
        "expires_at",
        "stale_until",
        "etag",
        "last_modified",
        "last_error",
    }.issubset(cols)
    meta_cols = {col["name"] for col in inspect(db.engine()).get_columns(ApiCacheMeta.__tablename__)}
    assert {"key", "value", "updated_at"}.issubset(meta_cols)


def test_init_schema_creates_tool_author_claim_tables():
    db.configure("sqlite://")
    db.init_schema()
    cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolAuthorClaim.__tablename__)}
    assert {
        "id",
        "tool_name",
        "author_name",
        "toolhub_username",
        "verification_status",
        "verification_method",
        "evidence_url",
        "evidence_payload",
        "checked_at",
        "expires_at",
        "last_error",
    }.issubset(cols)
    key_cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolAuthorKey.__tablename__)}
    assert {
        "id",
        "toolhub_username",
        "key_id",
        "public_key",
        "algorithm",
        "created_at",
        "revoked_at",
        "last_used_at",
    }.issubset(key_cols)
    with db.session_scope() as s:
        claim = ToolAuthorClaim(tool_name="toolforge-example", author_name="Display Name", toolhub_username="owner")
        key = ToolAuthorKey(toolhub_username="owner", key_id="k1", public_key="pk")
        s.add(claim)
        s.add(key)
        s.flush()
        assert claim.verification_status == sync.AUTHOR_CLAIM_UNVERIFIED
        assert claim.verification_method == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME
        assert claim.checked_at is not None
        assert key.algorithm == "ed25519"

    with pytest.raises(IntegrityError):
        with db.session_scope() as s:
            s.add(
                ToolAuthorClaim(
                    tool_name="toolforge-example",
                    author_name="Display Name",
                    toolhub_username="owner",
                    verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                )
            )


def test_toolforge_membership_provider_extracts_tool_names_from_member_dns():
    dns = [
        "cn=project-tools,ou=groups,dc=wikimedia,dc=org",
        "cn=tools.toolhub-evolved,ou=servicegroups,dc=wikimedia,dc=org",
        "cn=tools.blybot,ou=servicegroups,dc=wikimedia,dc=org",
        "cn=tools.toolhub-evolved,ou=servicegroups,dc=wikimedia,dc=org",
    ]
    assert toolforge_tool_names_from_member_dns(dns) == ["toolhub-evolved", "blybot"]
    provider = ToolforgeMembershipProvider(lookup=lambda username: dns if username == "Schiste" else [])
    assert provider.tool_names("Schiste") == ["toolhub-evolved", "blybot"]


def test_toolforge_membership_provider_handles_empty_missing_and_failing_ldap(monkeypatch):
    assert ToolforgeMembershipProvider(lookup=lambda _username: []).tool_names("") == []
    assert ToolforgeMembershipProvider(lookup=lambda _username: (_ for _ in ()).throw(ValueError("bad"))).tool_names(
        "Ada"
    ) == []
    monkeypatch.setattr(author_claims, "Connection", None)
    monkeypatch.setattr(author_claims, "Server", None)
    monkeypatch.setattr(author_claims, "escape_filter_chars", None)
    assert ToolforgeMembershipProvider().tool_names("Ada") == []


def test_toolforge_membership_provider_queries_ldap(monkeypatch):
    calls = {}

    class FakeServer:
        def __init__(self, uri, *, use_ssl, connect_timeout):
            calls["server"] = (uri, use_ssl, connect_timeout)

    class FakeMemberOf:
        values = ["cn=tools.toolhub-evolved,ou=servicegroups,dc=wikimedia,dc=org"]

    class FakeEntry:
        memberOf = FakeMemberOf()

    class FakeConnection:
        def __init__(self, server, *, receive_timeout, auto_bind):
            calls["connection"] = (server, receive_timeout, auto_bind)
            self.entries = []

        def search(self, base_dn, ldap_filter, *, attributes, size_limit):
            calls["search"] = (base_dn, ldap_filter, attributes, size_limit)
            self.entries = [FakeEntry()]

        def unbind(self):
            calls["unbind"] = True

    monkeypatch.setattr(author_claims, "Server", FakeServer)
    monkeypatch.setattr(author_claims, "Connection", FakeConnection)
    monkeypatch.setattr(author_claims, "escape_filter_chars", lambda value: f"escaped:{value}")
    assert ToolforgeMembershipProvider().tool_names("Schiste") == ["toolhub-evolved"]
    assert calls["server"] == (author_claims.TOOLFORGE_LDAP_URI, True, author_claims.TOOLFORGE_LDAP_TIMEOUT)
    assert author_claims.TOOLFORGE_LDAP_URI.startswith("ldaps://")  # never cleartext 389
    assert calls["search"] == (
        author_claims.TOOLFORGE_LDAP_BASE_DN,
        "(uid=escaped:Schiste)",
        ["memberOf"],
        1,
    )
    assert calls["unbind"] is True


def test_toolforge_membership_provider_handles_ldap_entries_without_member_of(monkeypatch):
    class FakeConnection:
        entries = []
        next_entries = []

        def __init__(self, *_args, **_kwargs):
            self.entries = self.next_entries

        def search(self, *_args, **_kwargs):
            pass

        def unbind(self):
            pass

    monkeypatch.setattr(author_claims, "Server", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(author_claims, "Connection", FakeConnection)
    monkeypatch.setattr(author_claims, "escape_filter_chars", lambda value: value)
    assert ToolforgeMembershipProvider().tool_names("Schiste") == []
    FakeConnection.next_entries = [object()]
    assert ToolforgeMembershipProvider().tool_names("Schiste") == []


def test_api_cache_recent_poll_baselines_marker_without_invalidating(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        api_cache.CacheableResponse(200, "application/json", b'{"name":"my-tool"}'),
    )

    first = [{}, {"id": 1, "timestamp": "2026-07-27T10:00:00Z", "content_type": "tool", "content_id": "my-tool"}]
    assert api_cache.maybe_poll_recent_changes(lambda: first) == 0
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 1
        assert s.get(ApiCacheMeta, "recent_latest_marker") is not None

    second = [{"id": 2, "timestamp": "2026-07-27T11:00:00Z", "content_type": "tool", "content_id": "my-tool"}]
    assert api_cache.maybe_poll_recent_changes(lambda: second) == 0
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 1


def test_api_cache_recent_poll_invalidates_changed_tool_and_list_rows(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    baseline = [{"id": 10, "timestamp": "2026-07-27T09:00:00Z", "content_type": "tool", "content_id": "old"}]
    assert api_cache.maybe_poll_recent_changes(lambda: baseline) == 0

    cached_urls = [
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        "https://toolhub.wikimedia.org/api/tools/my-tool/revisions/?page_size=20",
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        "https://toolhub.wikimedia.org/api/ui/home/",
        "https://toolhub.wikimedia.org/api/recent/?page_size=100",
        "https://toolhub.wikimedia.org/api/lists/77/",
        "https://toolhub.wikimedia.org/api/lists/?page=1",
        "https://toolhub.wikimedia.org/api/tools/other-tool/",
    ]
    for url in cached_urls:
        api_cache.put_success(url, api_cache.CacheableResponse(200, "application/json", b"{}"))
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)

    rows = [
        {"id": 12, "timestamp": "2026-07-27T11:00:00Z", "content_type": "list", "content_id": 77},
        {"id": 11, "timestamp": "2026-07-27T10:00:00Z", "content_type": "tool", "content_id": "my-tool"},
        {"id": 10, "timestamp": "2026-07-27T09:00:00Z", "content_type": "tool", "content_id": "old"},
    ]
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 7
    with db.session_scope() as s:
        assert [row.url for row in s.query(ApiCache).all()] == ["https://toolhub.wikimedia.org/api/tools/other-tool/"]


def test_api_cache_recent_poll_processes_page_when_old_marker_is_not_seen(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    baseline = [{"id": 1, "timestamp": "2026-07-27T09:00:00Z", "content_type": "tool", "content_id": "old"}]
    assert api_cache.maybe_poll_recent_changes(lambda: baseline) == 0
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)

    rows = [
        {"id": 3, "timestamp": "2026-07-27T11:00:00Z", "content_type": "tool", "content_id": "my-tool"},
        {"id": 2, "timestamp": "2026-07-27T10:00:00Z", "content_type": "tool"},
    ]
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 1
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 0


def test_api_cache_direct_invalidation_helpers_cover_noop_and_collection_paths(app):
    policy = api_cache.policy_for_url("https://toolhub.wikimedia.org/api/tools/my-tool/")
    assert policy.stale_until_seconds == policy.fresh_seconds + policy.stale_if_error_seconds
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/?page=1",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    api_cache.refresh("https://toolhub.wikimedia.org/api/missing/")
    assert api_cache.invalidate_tool("") == 0
    assert api_cache.invalidate_list("") == 0
    assert (
        api_cache.invalidate_recent_rows([{"content_type": "crawler_url", "content_id": "1"}, {"content_type": "tool"}])
        == 0
    )
    assert api_cache.invalidate_list_collection() == 1


def test_api_cache_recent_poll_handles_invalid_marker_empty_rows_and_fetch_errors(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    with db.session_scope() as s:
        s.add(ApiCacheMeta(key="recent_last_polled_at", value="not-a-date"))

    assert api_cache.maybe_poll_recent_changes(lambda: [{}]) == 0
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)
    assert api_cache.maybe_poll_recent_changes(lambda: (_ for _ in ()).throw(RuntimeError("boom"))) == 0


def test_api_cache_database_failures_do_not_break_callers(app, monkeypatch):
    @contextmanager
    def broken_session_scope():
        raise SQLAlchemyError("db down")
        yield

    monkeypatch.setattr(api_cache.db, "session_scope", broken_session_scope)
    assert api_cache.get("https://toolhub.wikimedia.org/api/tools/my-tool/") is None
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    api_cache.refresh("https://toolhub.wikimedia.org/api/tools/my-tool/")
    api_cache.mark_failure("https://toolhub.wikimedia.org/api/tools/my-tool/", "timeout")
    assert api_cache.invalidate_list_collection() == 0
    assert api_cache.maybe_poll_recent_changes(lambda: []) == 0


def test_api_cache_needs_refresh_assumes_stale_when_the_database_is_down(app, monkeypatch):
    @contextmanager
    def broken_session_scope():
        raise SQLAlchemyError("db down")
        yield

    monkeypatch.setattr(api_cache.db, "session_scope", broken_session_scope)
    # Fail towards refetching rather than serving something we cannot verify.
    assert api_cache.needs_refresh("https://toolhub.wikimedia.org/api/tools/my-tool/") is True


def test_owner_label_extraction_handles_every_shape_toolhub_returns():
    assert recent_owners.owner_from_tool_record("not-a-dict") == ""
    assert recent_owners.owner_from_tool_record({"author": [{"bio": "no usable key"}, {"name": "Ada"}]}) == "Ada"
    assert recent_owners.owner_from_tool_record({"author": [{"developer_username": "dev"}]}) == "dev"
    assert recent_owners.owner_from_tool_record({"author": ["", "  ", "Grace"]}) == "Grace"
    assert recent_owners.owner_from_tool_record({"author": [None, {"created": 1}], "created_by": {"username": "Bo"}}) == "Bo"
    assert recent_owners.owner_from_tool_record({"author": []}) == ""


def test_owner_cache_database_failures_do_not_break_the_recent_page(app, monkeypatch):
    @contextmanager
    def broken_session_scope():
        raise SQLAlchemyError("db down")
        yield

    monkeypatch.setattr(recent_owners.db, "session_scope", broken_session_scope)
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_a, **_k: {"name": "t", "author": [{"name": "Ada"}]})
    # Every path degrades to "no cache" rather than raising into the request.
    assert recent_owners._cached_owner("t") is None
    recent_owners._store_owner("t", "Ada")
    recent_owners._mark_failure("t", "boom")
    assert recent_owners.purge_expired() == 0
    assert recent_owners.resolve_owners(["t"])["owners"] == {"t": "Ada"}


def test_fully_expired_owner_row_is_treated_as_a_miss(client):
    now = utcnow()
    with db.session_scope() as s:
        # Past both windows but not yet swept by purge_expired().
        s.add(
            ToolOwnerCache(
                tool_name="ancient",
                owner="Stale Ada",
                fetched_at=now - timedelta(days=30),
                expires_at=now - timedelta(days=29),
                stale_until=now - timedelta(days=1),
            )
        )
    assert recent_owners._cached_owner("ancient") is None  # too old to serve, even as stale


def test_mark_failure_ignores_a_tool_with_no_cached_row(client):
    recent_owners._mark_failure("never-cached", "boom")  # no row → nothing to annotate
    with db.session_scope() as s:
        assert s.get(ToolOwnerCache, "never-cached") is None


def test_api_cache_recent_poll_keeps_removed_count_when_marker_write_fails(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )

    original_set_metadata = api_cache._set_metadata

    def flaky_set_metadata(*args):
        if args[1] == "recent_latest_marker":
            raise SQLAlchemyError("db down")
        return original_set_metadata(*args)

    monkeypatch.setattr(api_cache, "_set_metadata", flaky_set_metadata)
    rows = [{"id": 3, "timestamp": "2026-07-27T11:00:00Z", "content_type": "tool", "content_id": "my-tool"}]
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 0
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)
    with db.session_scope() as s:
        original_set_metadata(s, "recent_latest_marker", '{"id":"1","timestamp":"old"}', clock["t"])
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 1


def test_official_cache_invalidation_helper_handles_edge_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(api_cache, "invalidate_tool", lambda name: calls.append(("tool", name)))
    monkeypatch.setattr(api_cache, "invalidate_list", lambda ident: calls.append(("list", ident)))
    monkeypatch.setattr(api_cache, "invalidate_list_collection", lambda: calls.append(("lists", "*")))

    assert _string_payload_value("not-json", "name") is None
    assert _string_payload_value({"id": None, "name": " from-request "}, "id", "name") == "from-request"
    assert _string_payload_value({"id": "", "name": "from-empty-fallback"}, "id", "name") == "from-empty-fallback"
    _invalidate_official_api_cache("/not-api", None, None)
    _invalidate_official_api_cache("/api/tools/", {}, {})
    _invalidate_official_api_cache("/api/tools/", {"name": "from-request"}, ["not-a-dict"])
    _invalidate_official_api_cache("/api/lists/", {}, {})

    assert calls == [("tool", "from-request"), ("lists", "*")]


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
        conn.exec_driver_sql("CREATE TABLE lists (client_id VARCHAR(64) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tools (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_overlays (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE crawler_urls (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_thanks (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_health_targets (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_media (id INTEGER PRIMARY KEY)")
    db._upgrade_schema()
    user_columns = {col["name"] for col in inspect(eng).get_columns("users")}
    assert "role" in user_columns
    favorite_columns = {col["name"] for col in inspect(eng).get_columns("favorites")}
    assert {"created_by_user_id", "source", "sync_status", "last_synced_at", "last_error"}.issubset(favorite_columns)
    tool_columns = {col["name"] for col in inspect(eng).get_columns("tools")}
    assert {"created_by_user_id", "review_status", "deleted_at"}.issubset(tool_columns)
    list_columns = {col["name"] for col in inspect(eng).get_columns("lists")}
    assert {"last_toolhub_response", "validation_errors"}.issubset(list_columns)
    overlay_columns = {col["name"] for col in inspect(eng).get_columns("tool_overlays")}
    assert {"last_toolhub_response", "validation_errors"}.issubset(overlay_columns)
    crawler_columns = {col["name"] for col in inspect(eng).get_columns("crawler_urls")}
    assert {"last_toolhub_response", "validation_errors"}.issubset(crawler_columns)
    media_columns = {col["name"] for col in inspect(eng).get_columns("tool_media")}
    assert {"created_by_user_id", "review_status", "sync_status", "deleted_at"}.issubset(media_columns)
    thanks_columns = {col["name"] for col in inspect(eng).get_columns("tool_thanks")}
    assert {"created_by_user_id", "review_status", "source", "sync_status"}.issubset(thanks_columns)
    health_columns = {col["name"] for col in inspect(eng).get_columns("tool_health_targets")}
    assert {"source", "sync_status", "review_status", "last_synced_at", "deleted_at"}.issubset(health_columns)

    assert sync.clean_source("official") == "official"
    assert sync.clean_source("bogus") == "local"
    assert sync.clean_sync_status("sync_error") == "sync_error"
    assert sync.clean_sync_status("bogus") == "local_draft"
    assert sync.clean_review_status("approved") == "approved"
    assert sync.clean_review_status("bogus") == "pending"
    assert sync.clean_author_claim_status("verified") == "verified"
    assert sync.clean_author_claim_status("bogus") == "unverified"
    assert sync.clean_author_claim_method("toolforge_maintainer") == "toolforge_maintainer"
    assert sync.clean_author_claim_method("bogus") == "author_display_name"
    assert sync.clean_error(None) is None
    assert sync.clean_error("  upstream refused  ") == "upstream refused"
    assert sync.clean_error("   ") is None
    assert sync.clean_int(None) is None
    assert sync.clean_int("") is None
    assert sync.clean_int("42") == 42
    assert sync.clean_int(object()) is None
    assert sync.created_by_user_id(ToolList(created_by_user_id=7, user_id=8, client_id="l", title="L")) == 7
    assert sync.created_by_user_id(ToolList(user_id=8, client_id="legacy", title="L")) == 8
    assert sync.created_by_user_id(object()) is None

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


def test_toolhub_author_names_ignore_unknown_author_shapes():
    assert _toolhub_author_names({"author": [None], "modified_by": {"username": "Ada"}}) == ["Ada"]


def test_author_name_provider_records_unverified_claims(client):
    user = User(id=7, wm_sub="7", username="Ada")
    with db.session_scope() as s:
        rows = AuthorNameProvider().record(
            s,
            user,
            tool_name="ada-tool",
            author_names=["Ada", "ada", ""],
            evidence_url="https://toolhub.example/search",
            evidence_payload={"searchTerms": ["Ada"]},
        )
        assert len(rows) == 1
        payload = author_claims.claim_payload(rows[0])
        assert payload["verificationStatus"] == sync.AUTHOR_CLAIM_UNVERIFIED
        assert payload["verificationMethod"] == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME
        assert payload["isVerified"] is False
        forced = author_claims.record_author_claim(
            s,
            tool_name="ada-tool",
            author_name="Ada",
            toolhub_username="Ada",
            verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
        )
        assert forced.verification_status == sync.AUTHOR_CLAIM_UNVERIFIED


def test_claim_payload_marks_expired_verified_claims_stale(client):
    with db.session_scope() as s:
        row = ToolAuthorClaim(
            tool_name="stale-tool",
            author_name="Ada",
            toolhub_username="Ada",
            verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            verification_method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
            expires_at=utcnow() - timedelta(seconds=1),
        )
        s.add(row)
        s.flush()
        payload = author_claims.claim_payload(row)
    assert payload["verificationStatus"] == sync.AUTHOR_CLAIM_STALE
    assert payload["isVerified"] is False


def test_toolforge_maintainer_provider_verifies_matching_maintainer(client):
    uid = add_user(username="schiste")
    user = User(id=uid, wm_sub="42", username="schiste")
    calls = []

    def fetch_toolsadmin(name):
        calls.append(name)
        return 200, TOOLSADMIN_MAINTAINERS_TABLE_HTML

    provider = ToolforgeMaintainerProvider(fetcher=fetch_toolsadmin)
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolhub-evolved",
            author_names=["Christophe"],
            toolhub_tool={"url": "https://toolhub-evolved.toolforge.org"},
        )
        assert len(rows) == 1
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert rows[0].verification_method == sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER
        provider.verify(
            s,
            user,
            tool_name="toolhub-evolved",
            author_names=["Christophe"],
            toolhub_tool={"url": "https://toolhub-evolved.toolforge.org"},
        )
    assert calls == ["toolhub-evolved"]


def test_toolforge_maintainer_provider_retries_failed_claims(client):
    uid = add_user(username="schiste")
    user = User(id=uid, wm_sub="42", username="schiste")
    with db.session_scope() as s:
        author_claims.record_author_claim(
            s,
            tool_name="toolhub-evolved",
            author_name="Christophe",
            toolhub_username="schiste",
            verification_status=sync.AUTHOR_CLAIM_FAILED,
            verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
            expires_at=utcnow() + timedelta(days=1),
            last_error="user is not listed as a Toolforge maintainer",
        )
        calls = []
        rows = ToolforgeMaintainerProvider(
            fetcher=lambda name: calls.append(name) or (200, TOOLSADMIN_MAINTAINERS_TABLE_HTML)
        ).verify(
            s,
            user,
            tool_name="toolhub-evolved",
            author_names=["Christophe"],
            toolhub_tool={"url": "https://toolhub-evolved.toolforge.org"},
        )
        assert len(rows) == 1
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert rows[0].last_error is None
    assert calls == ["toolhub-evolved"]


def test_author_claim_provider_parsers_cover_malformed_public_shapes():
    assert author_claims.parse_toolsadmin_maintainers(TOOLSADMIN_MAINTAINERS_TABLE_HTML) == ["Schiste"]
    assert author_claims.parse_toolsadmin_maintainers(
        '<table><tr><td>Not a maintainer</td></tr></table>'
        "<table><caption>Other</caption><tbody><tr><td>Also not</td></tr></tbody></table>"
        '<table><caption>Maintainers</caption><tbody><tr><td>'
        '<a href="/profile/ada/">Ada Lovelace</a></td></tr></tbody></table>'
    ) == ["Ada Lovelace"]
    assert author_claims.parse_toolsadmin_maintainers('<a href="/profile/blank/"> </a>') == []
    assert author_claims.parse_toolsadmin_maintainers("<p>No maintainers here</p>") == []
    assert author_claims.author_names_from_toolinfo({"author": "Ada"}) == ["Ada"]
    assert author_claims.author_names_from_toolinfo({"author": [None]}) == []
    assert author_claims.toolforge_names_from_toolhub_tool(
        "plain",
        {"api_url": "https://toolsadmin.wikimedia.org/tools/id/from-api/toolinfo/1.2/toolinfo.json"},
    ) == ["from-api"]
    assert (
        author_claims.toolforge_names_from_toolhub_tool(
            "plain",
            {"api_url": "https://toolsadmin.wikimedia.org/tools/id"},
        )
        == []
    )
    assert author_claims.signature_meta({"x_toolhub_evolved_signature": {"key_id": "k1"}}) is None


def test_toolforge_maintainer_provider_records_failures(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    provider = ToolforgeMaintainerProvider(fetcher=lambda name: (500, "down"))
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-alpha",
            author_names=["Ada"],
            toolhub_tool={},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "500" in rows[0].last_error
    provider = ToolforgeMaintainerProvider(
        fetcher=lambda name: (200, "Maintainers\nMaintainers\nOther\nGit repositories")
    )
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-beta",
            author_names=["Ada"],
            toolhub_tool={},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "not listed" in rows[0].last_error


def test_toolforge_maintainer_provider_tries_next_name_after_404(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    calls = []

    def fetcher(name):
        calls.append(name)
        return (404, "") if name == "alpha" else (200, '<a href="/profile/ada/">Ada</a>')

    provider = ToolforgeMaintainerProvider(fetcher=fetcher)
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-alpha",
            author_names=["Ada"],
            toolhub_tool={"url": "https://beta.toolforge.org"},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
    assert calls == ["alpha", "beta"]


def test_toolforge_maintainer_provider_records_fetch_errors(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")

    def fetcher(_name):
        raise toolhub.requests.ConnectionError("offline")

    with db.session_scope() as s:
        rows = ToolforgeMaintainerProvider(fetcher=fetcher).verify(
            s,
            user,
            tool_name="toolforge-alpha",
            author_names=[],
            toolhub_tool={},
        )
        assert rows[0].author_name == "Ada"
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "offline" in rows[0].last_error


def test_toolforge_provider_skips_non_toolforge_candidates(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    with db.session_scope() as s:
        assert (
            ToolforgeMaintainerProvider(fetcher=lambda name: pytest.fail("should not fetch")).verify(
                s,
                user,
                tool_name="plain-tool",
                author_names=["Ada"],
                toolhub_tool={"url": "https://example.org"},
            )
            == []
        )


def test_toolhub_write_provider_records_tool_write_claims(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    provider = ToolhubWriteProvider()
    with db.session_scope() as s:
        assert (
            provider.record_success(
                s,
                user,
                method="POST",
                path="/api/lists/",
                request_payload={"title": "L"},
                response_payload={"id": 1},
            )
            == []
        )
        rows = provider.record_success(
            s,
            user,
            method="PUT",
            path="/api/tools/ada-tool/annotations/",
            request_payload={},
            response_payload={"name": "ada-tool", "author": [{"name": "Ada Lovelace"}]},
        )
        assert rows[0].author_name == "Ada Lovelace"
        assert rows[0].verification_method == sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS
        assert rows[0].evidence_url == "https://toolhub.example/api/tools/ada-tool/"
        rows = provider.record_success(
            s,
            user,
            method="POST",
            path="/api/tools/",
            request_payload={"name": "created-tool"},
            response_payload={},
        )
        assert rows[0].author_name == "Ada"


def test_successful_toolhub_write_provider_errors_are_non_fatal(client, monkeypatch):
    class RaisingProvider:
        def record_success(self, *args, **kwargs):
            raise RuntimeError("claim storage down")

    monkeypatch.setattr(v1_api, "TOOLHUB_WRITE_PROVIDER", RaisingProvider())
    v1_api._record_successful_toolhub_write(  # noqa: SLF001 - tests private non-fatal side effect
        User(id=1, wm_sub="1", username="Ada"),
        "POST",
        "/api/tools/",
        {"name": "ada-tool"},
        {"name": "ada-tool"},
    )


def test_signed_toolinfo_provider_verifies_registered_key(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    sig = "c2ln"
    toolinfo = {
        "name": "signed-tool",
        "title": "Signed",
        "author": [{"name": "Ada Lovelace"}],
        "x_toolhub_evolved_signature": {"key_id": "k1", "signature": sig},
    }
    calls = []

    def verifier(public_key, signature, message):
        calls.append((public_key, signature, message))

    with db.session_scope() as s:
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
        rows = SignedToolinfoProvider(verifier).verify(
            s,
            user,
            toolinfo=toolinfo,
            evidence_url="https://example.org/toolinfo.json",
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert rows[0].verification_method == sync.AUTHOR_CLAIM_SIGNED_TOOLINFO
        assert rows[0].evidence_payload["signaturePrefix"] == sig
        assert s.query(ToolAuthorKey).one().last_used_at is not None
    assert calls == [
        (
            "pk",
            b"sig",
            b'{"author":[{"name":"Ada Lovelace"}],"name":"signed-tool","title":"Signed"}',
        )
    ]


def test_signed_toolinfo_provider_records_failures(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    provider = SignedToolinfoProvider(lambda *_args: None)
    base = {"name": "signed-tool", "author": "Ada"}
    with db.session_scope() as s:
        assert provider.verify(s, user, toolinfo={"name": "unsigned"}) == []
        assert (
            provider.verify(s, user, toolinfo={"x_toolhub_evolved_signature": {"key_id": "k1", "signature": "xx"}})
            == []
        )
        rows = provider.verify(
            s,
            user,
            toolinfo={
                **base,
                "x-toolhub-evolved-signature": {"keyId": "missing", "signature": "c2ln"},
            },
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert rows[0].last_error == "public key not found"
        rows = provider.verify(
            s,
            user,
            toolinfo={**base, "x_toolhub_evolved_signature": {"key_id": "k1", "algorithm": "rsa", "signature": "c2ln"}},
        )
        assert rows[0].last_error == "unsupported signature algorithm"
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
        rows = provider.verify(
            s,
            user,
            toolinfo={**base, "x_toolhub_evolved_signature": {"key_id": "k1", "signature": "***"}},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "Only base64 data" in rows[0].last_error


def test_signed_toolinfo_provider_records_verifier_failure(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")

    def verifier(*_args):
        raise ValueError("bad signature")

    with db.session_scope() as s:
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
        rows = SignedToolinfoProvider(verifier).verify(
            s,
            user,
            toolinfo={
                "name": "signed-tool",
                "author": [],
                "x_toolhub_evolved_signature": {"key_id": "k1", "signature": "c2ln"},
            },
        )
        assert rows[0].author_name == "Ada"
        assert rows[0].last_error == "bad signature"


def test_ed25519_public_key_validation_without_crypto_dependency(monkeypatch):
    monkeypatch.setattr(author_claims, "Ed25519PublicKey", None)
    monkeypatch.setattr(author_claims, "load_pem_public_key", None)
    valid_raw = b64encode(b"1" * 32).decode("ascii")
    assert author_claims.validate_ed25519_public_key(valid_raw) == valid_raw
    valid_pem = "-----BEGIN PUBLIC KEY-----\nplaceholder\n-----END PUBLIC KEY-----"
    assert author_claims.validate_ed25519_public_key(valid_pem) == valid_pem
    with pytest.raises(ValueError, match="required"):
        author_claims.validate_ed25519_public_key("")
    with pytest.raises(ValueError, match="not a private key"):
        author_claims.validate_ed25519_public_key("-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----")
    with pytest.raises(ValueError, match="PUBLIC KEY"):
        author_claims.validate_ed25519_public_key("-----BEGIN CERTIFICATE-----\nnope\n-----END CERTIFICATE-----")
    with pytest.raises(ValueError, match="PEM or base64"):
        author_claims.validate_ed25519_public_key("***")
    with pytest.raises(ValueError, match="32 bytes"):
        author_claims.validate_ed25519_public_key(b64encode(b"short").decode("ascii"))


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
    assert data["authenticated"] is True
    assert data["username"] == "Ada"
    assert data["csrf"] == "tok"
    assert data["evolvedRole"] == "user"
    assert data["evolvedRoleLabel"] == "Signed-in user"
    assert authz.ACTION_PRIVATE_WRITE in data["evolvedPermissions"]


def test_author_keys_require_login_and_csrf(client):
    assert client.get("/v1/author-keys/").status_code == 401
    uid = add_user()
    sign_in(client, uid)
    assert client.post("/v1/author-keys/", json={"keyId": "k1", "publicKey": "pk"}).status_code == 403
    assert client.delete("/v1/author-keys/k1/").status_code == 403


def test_author_key_lifecycle(client):
    uid = add_user()
    sign_in(client, uid)
    public_key = b64encode(b"1" * 32).decode("ascii")
    resp = client.post(
        "/v1/author-keys/",
        json={"keyId": "release-2026", "publicKey": public_key},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["key"]["keyId"] == "release-2026"
    assert data["key"]["algorithm"] == "ed25519"
    assert data["key"]["fingerprint"].startswith("SHA256:")
    assert data["key"]["revokedAt"] == ""

    listed = client.get("/v1/author-keys/").get_json()
    assert listed["username"] == "Ada"
    assert listed["keys"][0]["keyId"] == "release-2026"

    duplicate = client.post(
        "/v1/author-keys/",
        json={"keyId": "release-2026", "publicKey": public_key},
        headers={"X-CSRF-Token": "tok"},
    )
    assert duplicate.status_code == 409

    revoked = client.delete("/v1/author-keys/release-2026/", headers={"X-CSRF-Token": "tok"}).get_json()
    assert revoked["key"]["revokedAt"].endswith("Z")


def test_author_key_registration_validates_input(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.post("/v1/author-keys/", data="not json", headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert (
        client.post(
            "/v1/author-keys/",
            json={"keyId": "bad key", "publicKey": b64encode(b"1" * 32).decode("ascii")},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/author-keys/",
            json={"keyId": "k1", "algorithm": "rsa", "publicKey": b64encode(b"1" * 32).decode("ascii")},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    resp = client.post(
        "/v1/author-keys/",
        json={"keyId": "k1", "publicKey": "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert "public key" in resp.get_json()["error"]


def test_author_key_revoke_reports_bad_or_missing_keys(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.delete("/v1/author-keys/bad%20key/", headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert client.delete("/v1/author-keys/missing/", headers={"X-CSRF-Token": "tok"}).status_code == 404
    with db.session_scope() as s:
        s.add(
            ToolAuthorKey(
                toolhub_username="Ada",
                key_id="revoked",
                public_key=b64encode(b"1" * 32).decode("ascii"),
                revoked_at=utcnow(),
            )
        )
    resp = client.delete("/v1/author-keys/revoked/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json()["key"]["revokedAt"].endswith("Z")


def test_toolinfo_signing_payload_uses_registered_active_key(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key=b64encode(b"1" * 32).decode("ascii")))
    toolinfo = {
        "title": "Signed",
        "name": "signed-tool",
        "author": [{"name": "Ada"}],
        "x_toolhub_evolved_signature": {"key_id": "old", "signature": "old"},
    }
    resp = client.post(
        "/v1/toolinfo/signing-payload/",
        json={"keyId": "k1", "toolinfo": toolinfo},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["toolName"] == "signed-tool"
    assert data["signatureField"] == "x_toolhub_evolved_signature"
    assert data["signatureMetadata"] == {
        "algorithm": "ed25519",
        "key_id": "k1",
        "signature": "<base64 signature>",
    }
    assert data["canonicalPayload"] == '{"author":[{"name":"Ada"}],"name":"signed-tool","title":"Signed"}'
    assert data["canonicalPayloadBase64"] == b64encode(data["canonicalPayload"].encode()).decode("ascii")
    assert data["signedToolinfoPreview"]["x_toolhub_evolved_signature"] == data["signatureMetadata"]


def test_toolinfo_signing_payload_rejects_missing_or_revoked_key(client):
    uid = add_user()
    sign_in(client, uid)
    assert (
        client.post("/v1/toolinfo/signing-payload/", data="not json", headers={"X-CSRF-Token": "tok"}).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "bad key", "toolinfo": {"name": "signed-tool"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "missing", "toolinfo": "["},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "missing", "toolinfo": []},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "missing", "toolinfo": {"name": "signed-tool"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 404
    )
    with db.session_scope() as s:
        s.add(
            ToolAuthorKey(
                toolhub_username="Ada",
                key_id="revoked",
                public_key=b64encode(b"1" * 32).decode("ascii"),
                revoked_at=utcnow(),
            )
        )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "revoked", "toolinfo": {"name": "signed-tool"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "revoked", "toolinfo": {"title": "missing name"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )


def test_me_tools_requires_login(client):
    assert client.get("/v1/me/tools/").status_code == 401


def test_me_tools_returns_possible_display_author_matches(client, monkeypatch):
    uid = add_user(username="Ada Lovelace")
    sign_in(client, uid)
    calls = []

    def fake_public_api_get(path, *, params=None):
        calls.append((path, params))
        return {
            "results": [
                {
                    "name": "ada-tool",
                    "title": "Ada Tool",
                    "author": "Ada Lovelace",
                    "created_by": {"username": "Toolhub"},
                    "modified_by": {"username": "Ada Lovelace"},
                },
                {"title": "Nameless", "author": [{"name": "Ada Lovelace"}]},
            ]
        }

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    resp = client.get("/v1/me/tools/")
    data = resp.get_json()
    assert resp.status_code == 200
    assert calls == [
        (
            "/api/search/tools/",
            {"author__term": "Ada Lovelace", "ordering": "-score", "page": 1, "page_size": 100},
        )
    ]
    assert data["username"] == "Ada Lovelace"
    assert data["counts"] == {"verified": 0, "possible": 1}
    assert data["verified"] == []
    item = data["possible"][0]
    assert item["tool"]["name"] == "ada-tool"
    assert item["matchedAuthorNames"] == ["Ada Lovelace"]
    assert item["claims"][0]["verificationStatus"] == sync.AUTHOR_CLAIM_UNVERIFIED
    assert item["claims"][0]["verificationMethod"] == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME
    assert item["claims"][0]["isVerified"] is False


def test_me_tools_uses_local_author_claims_as_verified_search_terms(client, monkeypatch):
    uid = add_user(username="schiste")
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(
            ToolAuthorClaim(
                tool_name="toolhub-evolved",
                author_name="Christophe",
                toolhub_username="schiste",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                evidence_url="https://toolsadmin.wikimedia.org/tools/id/toolhub-evolved",
                evidence_payload={"maintainer": "Schiste"},
            )
        )
    calls = []

    def fake_public_api_get(path, *, params=None):
        calls.append(params["author__term"])
        if params["author__term"] == "schiste":
            raise toolhub.ToolhubAPIError(503, {"message": "busy"})
        if params["author__term"] == "Christophe":
            return {
                "results": [
                    {
                        "name": "toolhub-evolved",
                        "title": "Toolhub Evolved",
                        "author": [{"name": "Christophe"}],
                    }
                ]
            }
        return {"results": []}

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    data = client.get("/v1/me/tools/").get_json()
    assert calls == ["schiste", "Christophe"]
    assert data["searchTerms"] == ["schiste", "Christophe"]
    assert data["counts"] == {"verified": 1, "possible": 0}
    assert data["errors"] == [{"term": "schiste", "status": 503, "details": {"message": "busy"}}]
    item = data["verified"][0]
    assert item["tool"]["name"] == "toolhub-evolved"
    assert item["matchedAuthorNames"] == ["Christophe"]
    assert any(
        claim["verificationMethod"] == sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER and claim["isVerified"]
        for claim in item["claims"]
    )


def test_me_tools_discovers_toolforge_memberships_when_author_name_differs(client, monkeypatch):
    uid = add_user(username="Schiste")
    sign_in(client, uid)
    monkeypatch.setattr(
        v1_api,
        "TOOLFORGE_MEMBERSHIP_PROVIDER",
        ToolforgeMembershipProvider(
            lookup=lambda username: [
                "cn=tools.toolhub-evolved,ou=servicegroups,dc=wikimedia,dc=org",
                "cn=tools.blybot,ou=servicegroups,dc=wikimedia,dc=org",
                "cn=tools.missing,ou=servicegroups,dc=wikimedia,dc=org",
            ]
        ),
    )
    monkeypatch.setattr(
        v1_api,
        "TOOLFORGE_MAINTAINER_PROVIDER",
        ToolforgeMaintainerProvider(fetcher=lambda _name: (200, TOOLSADMIN_MAINTAINERS_TABLE_HTML)),
    )
    calls = []

    def fake_public_api_get(path, *, params=None):
        calls.append((path, params))
        if path == "/api/search/tools/":
            assert params["author__term"] == "Schiste"
            return {"results": []}
        if path == "/api/tools/toolforge-toolhub-evolved/":
            return {
                "name": "toolforge-toolhub-evolved",
                "title": "Toolhub Evolved",
                "url": "https://toolsadmin.wikimedia.org/tools/id/toolhub-evolved",
                "author": [{"name": "Christophe"}],
            }
        if path == "/api/tools/toolforge-blybot/":
            return {
                "name": "toolforge-blybot",
                "title": "Bly bot",
                "url": "https://toolsadmin.wikimedia.org/tools/id/blybot",
                "author": [{"name": "Christophe"}],
            }
        if path == "/api/tools/toolforge-missing/":
            raise toolhub.ToolhubAPIError(404, {"detail": "not found"})
        raise AssertionError(path)

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    data = client.get("/v1/me/tools/").get_json()
    assert data["searchTerms"] == ["Schiste"]
    assert data["toolforgeToolNames"] == ["toolhub-evolved", "blybot", "missing"]
    assert data["counts"] == {"verified": 2, "possible": 0}
    assert [item["tool"]["name"] for item in data["verified"]] == ["toolforge-toolhub-evolved", "toolforge-blybot"]
    assert data["verified"][0]["matchedAuthorNames"] == ["Christophe"]
    assert "toolforge:toolhub-evolved" in data["verified"][0]["searchTerms"]
    assert data["verified"][0]["evidenceUrl"].endswith("/tools/id/toolhub-evolved")
    assert any(
        claim["authorName"] == "Christophe"
        and claim["verificationMethod"] == sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER
        and claim["isVerified"]
        for claim in data["verified"][0]["claims"]
    )
    assert ("/api/tools/toolforge-missing/", None) in calls


def test_toolforge_membership_candidate_fetch_handles_invalid_and_failed_toolhub_rows(monkeypatch):
    monkeypatch.setattr(
        v1_api,
        "TOOLFORGE_MEMBERSHIP_PROVIDER",
        ToolforgeMembershipProvider(
            lookup=lambda _username: [
                "cn=tools.invalid,ou=servicegroups,dc=wikimedia,dc=org",
                "cn=tools.busy,ou=servicegroups,dc=wikimedia,dc=org",
                "cn=tools.down,ou=servicegroups,dc=wikimedia,dc=org",
                "cn=tools.missing,ou=servicegroups,dc=wikimedia,dc=org",
            ]
        ),
    )

    def fake_detail(name):
        if name == "toolforge-invalid":
            return None
        if name == "toolforge-busy":
            raise toolhub.ToolhubAPIError(503, {"message": "busy"})
        if name == "toolforge-down":
            raise toolhub.requests.ConnectionError("down")
        if name == "toolforge-missing":
            raise toolhub.ToolhubAPIError(404, {"message": "missing"})
        raise AssertionError(name)

    monkeypatch.setattr(v1_api, "_toolhub_tool_detail", fake_detail)
    candidates, errors, names = v1_api._candidate_tools_for_toolforge_memberships("Schiste")
    assert candidates == {}
    assert names == ["invalid", "busy", "down", "missing"]
    assert errors == [
        {"term": "toolforge-busy", "status": 503, "details": {"message": "busy"}},
        {"term": "toolforge-down", "status": 502, "details": {"message": "down"}},
    ]
    v1_api._add_toolforge_candidate({}, {"title": "Nameless"}, "bad", "Schiste")


def test_me_tools_merges_author_search_and_toolforge_membership_candidates(client, monkeypatch):
    uid = add_user(username="Schiste")
    sign_in(client, uid)
    monkeypatch.setattr(
        v1_api,
        "TOOLFORGE_MEMBERSHIP_PROVIDER",
        ToolforgeMembershipProvider(
            lookup=lambda _username: ["cn=tools.toolhub-evolved,ou=servicegroups,dc=wikimedia,dc=org"]
        ),
    )
    monkeypatch.setattr(
        v1_api,
        "TOOLFORGE_MAINTAINER_PROVIDER",
        ToolforgeMaintainerProvider(fetcher=lambda _name: (200, TOOLSADMIN_MAINTAINERS_TABLE_HTML)),
    )

    def fake_public_api_get(path, *, params=None):
        if path == "/api/search/tools/":
            return {
                "results": [
                    {
                        "name": "toolforge-toolhub-evolved",
                        "title": "Toolhub Evolved",
                        "url": "https://toolsadmin.wikimedia.org/tools/id/toolhub-evolved",
                        "author": [{"name": "Schiste"}],
                    }
                ]
            }
        if path == "/api/tools/toolforge-toolhub-evolved/":
            return {
                "name": "toolforge-toolhub-evolved",
                "title": "Toolhub Evolved",
                "url": "https://toolsadmin.wikimedia.org/tools/id/toolhub-evolved",
                "author": [{"name": "Christophe"}],
            }
        raise AssertionError(path)

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    data = client.get("/v1/me/tools/").get_json()
    assert data["counts"] == {"verified": 1, "possible": 0}
    item = data["verified"][0]
    assert item["matchedAuthorNames"] == ["Schiste", "Christophe"]
    assert item["searchTerms"] == ["Schiste", "toolforge:toolhub-evolved"]
    assert item["evidenceUrl"].endswith("/tools/id/toolhub-evolved")


def test_me_tools_merges_toolforge_candidate_without_optional_evidence(client, monkeypatch):
    uid = add_user(username="Ada")
    sign_in(client, uid)
    row = {"name": "toolforge-ada", "title": "Ada", "author": [{"name": "Ada"}]}
    monkeypatch.setattr(toolhub, "public_api_get", lambda *args, **kwargs: {"results": [row]})
    monkeypatch.setattr(
        v1_api,
        "_candidate_tools_for_toolforge_memberships",
        lambda _username: (
            {
                "toolforge-ada": {
                    "tool": row,
                    "matchedAuthorNames": ["Ada"],
                    "searchTerms": ["toolforge:ada"],
                }
            },
            [],
            ["ada"],
        ),
    )
    monkeypatch.setattr(
        v1_api,
        "TOOLFORGE_MAINTAINER_PROVIDER",
        ToolforgeMaintainerProvider(fetcher=lambda _name: (404, "")),
    )
    data = client.get("/v1/me/tools/").get_json()
    assert data["counts"] == {"verified": 0, "possible": 1}
    assert data["possible"][0]["searchTerms"] == ["Ada", "toolforge:ada"]


def test_me_tools_verified_author_claims_are_per_tool_not_global(client, monkeypatch):
    uid = add_user(username="schiste")
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(
            ToolAuthorClaim(
                tool_name="toolhub-evolved",
                author_name="Christophe",
                toolhub_username="schiste",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
                evidence_url="https://toolhub.wikimedia.org/tools/toolhub-evolved",
                evidence_payload={"method": "PUT"},
            )
        )

    def fake_public_api_get(path, *, params=None):
        if params["author__term"] == "schiste":
            return {"results": []}
        return {
            "results": [
                {
                    "name": "toolhub-evolved",
                    "title": "Toolhub Evolved",
                    "author": [{"name": "Christophe"}],
                },
                {
                    "name": "same-author-other-tool",
                    "title": "Same Author Other Tool",
                    "author": [{"name": "Christophe"}],
                },
            ]
        }

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    data = client.get("/v1/me/tools/").get_json()
    assert data["searchTerms"] == ["schiste", "Christophe"]
    assert data["counts"] == {"verified": 1, "possible": 1}
    assert data["verified"][0]["tool"]["name"] == "toolhub-evolved"
    possible = data["possible"][0]
    assert possible["tool"]["name"] == "same-author-other-tool"
    assert all(claim["verificationMethod"] != sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS for claim in possible["claims"])
    assert any(
        claim["verificationMethod"] == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME and not claim["isVerified"]
        for claim in possible["claims"]
    )


def test_me_tools_toolforge_provider_upgrades_display_name_claim(client, monkeypatch):
    uid = add_user(username="schiste")
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(
            ToolAuthorClaim(
                tool_name="toolhub-evolved",
                author_name="Christophe",
                toolhub_username="schiste",
                verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
            )
        )

    def fake_public_api_get(path, *, params=None):
        if params["author__term"] == "Christophe":
            return {
                "results": [
                    {
                        "name": "toolhub-evolved",
                        "title": "Toolhub Evolved",
                        "url": "https://toolhub-evolved.toolforge.org",
                        "author": [{"name": "Christophe"}],
                    }
                ]
            }
        return {"results": []}

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    monkeypatch.setattr(
        author_claims.requests,
        "get",
        lambda *a, **k: type("Resp", (), {"status_code": 200, "text": '<a href="/profile/schiste/">Schiste</a>'})(),
    )
    data = client.get("/v1/me/tools/").get_json()
    assert data["counts"] == {"verified": 1, "possible": 0}
    claims = data["verified"][0]["claims"]
    assert any(
        claim["authorName"] == "Christophe"
        and claim["verificationMethod"] == sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER
        and claim["isVerified"]
        for claim in claims
    )


def test_me_tools_never_treats_display_author_claim_as_verified(client, monkeypatch):
    uid = add_user(username="Ada")
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada",
                toolhub_username="Ada",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
            )
        )

    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda *args, **kwargs: {"results": [{"name": "ada-tool", "author": [{"name": "Ada"}]}]},
    )
    data = client.get("/v1/me/tools/").get_json()
    assert data["counts"] == {"verified": 0, "possible": 1}
    assert data["possible"][0]["claims"][0]["verificationStatus"] == sync.AUTHOR_CLAIM_UNVERIFIED
    assert data["possible"][0]["claims"][0]["verificationMethod"] == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME
    assert data["possible"][0]["claims"][0]["isVerified"] is False


def test_me_tools_reports_upstream_failure_when_all_searches_fail(client, monkeypatch):
    uid = add_user(username="Ada")
    sign_in(client, uid)

    def fail_public_api_get(*args, **kwargs):
        raise toolhub.requests.ConnectionError("down")

    monkeypatch.setattr(toolhub, "public_api_get", fail_public_api_get)
    resp = client.get("/v1/me/tools/")
    assert resp.status_code == 502
    data = resp.get_json()
    assert data["error"] == "official Toolhub is unavailable"
    assert data["username"] == "Ada"
    assert data["errors"][0]["status"] == 502


def test_overlay_get_requires_login(client):
    assert client.get("/v1/overlay/").status_code == 401


def test_overlay_get_rejects_stale_policy_user(client):
    sign_in(client, 999)
    resp = client.get("/v1/overlay/")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "sign in required"}


def test_put_requires_login(client):
    assert client.put("/v1/overlay/favorites", json=[]).status_code == 401


def test_put_requires_csrf(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.put("/v1/overlay/favorites", json=[]).status_code == 403  # missing header
    assert put_overlay(client, "favorites", [], csrf="wrong").status_code == 403  # mismatch


def test_put_rejects_csrf_when_session_holds_no_usable_token(client):
    uid = add_user()
    for stored in (None, "", 1234):  # absent, empty, and non-string all fail closed
        sign_in(client, uid)
        with client.session_transaction() as sess:
            sess["csrf"] = stored
        assert put_overlay(client, "favorites", [], csrf="tok").status_code == 403


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


def test_rate_limit_prunes_stale_entries_for_active_user(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    security._writes.last_sweep = clock["t"]
    security._writes.times[uid] = deque([clock["t"] - security.WRITE_WINDOW_SECONDS - 1])
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    assert list(security._writes.times[uid]) == [clock["t"]]


def test_rate_limit_table_evicts_idle_users(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    security._writes.times[999] = deque()  # an entry whose window already drained
    assert uid in security._writes.times
    clock["t"] += security.WRITE_WINDOW_SECONDS + 1  # idle past the window → swept
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    assert 999 not in security._writes.times
    assert list(security._writes.times) == [uid]  # only the active writer is retained


def test_sign_out_strands_session_cookies_issued_before_it(client, app):
    uid = add_user()
    sign_in(client, uid)
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    stolen = app.test_client()  # a copy of the cookie taken while it was valid
    sign_in(stolen, uid)
    client.post("/oauth/logout", data={"csrf": "tok"})
    assert put_overlay(stolen, "favorites", ["b"]).status_code == 401  # epoch bumped → stale
    assert stolen.get("/v1/user/").get_json() == {"authenticated": False}


def test_policy_denial_blocks_private_overlay_writes(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(authz, "can", lambda *_args, **_kwargs: False)
    resp = put_overlay(client, "favorites", ["a"])
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "not allowed"}
    with db.session_scope() as s:
        assert s.query(Favorite).count() == 0
        assert s.query(ToolList).count() == 0
        assert s.query(ToolRecord).count() == 0
        assert s.query(CrawlerUrl).count() == 0


def test_policy_denial_blocks_public_evolved_writes(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(authz, "can", lambda *_args, **_kwargs: False)

    assert (
        client.post("/v1/tools/alpha/events/", json={"eventType": "view"}, headers={"X-CSRF-Token": "tok"}).status_code
        == 403
    )
    assert client.post("/v1/tools/alpha/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/healthz"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/tools/alpha/media/",
            json={"url": "https://img.example/shot.png", "license": "CC0", "source": "Maintainer"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 403
    )
    with db.session_scope() as s:
        assert s.query(ToolEvent).count() == 0
        assert s.query(ToolThanks).count() == 0
        assert s.query(ToolHealthTarget).count() == 0
        assert s.query(ToolMedia).count() == 0


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
    assert data["toolNew"]["my-tool"]["reviewStatus"] == "pending"
    assert data["revisions"] == revs
    assert data["auditlogs"][0]["action"] == "edited"
    with db.session_scope() as s:
        for model in (Favorite, ToolList, CrawlerUrl, ToolOverlay, ToolRecord, ActivityRow):
            assert {row.created_by_user_id for row in s.query(model)} == {uid}


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
                    "toolhubResponse": {"id": 77},
                    "validationErrors": [{"field": "title"}],
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
                    "toolhubResponse": {"id": 88},
                    "validationErrors": [{"field": "url"}],
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
                    "reviewStatus": "approved",
                    "lastError": "needs merge",
                    "toolhubResponse": {"message": "bad"},
                    "validationErrors": [{"field": "title"}],
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
    assert data["lists"][0]["toolhubResponse"] == {"id": 77}
    assert data["lists"][0]["validationErrors"] == [{"field": "title"}]
    assert data["crawlerUrls"][0]["officialId"] == 88
    assert data["crawlerUrls"][0]["id"] == 88
    assert data["crawlerUrls"][0]["lastSyncedAt"] == "2026-07-26T11:00:00Z"
    assert data["crawlerUrls"][0]["toolhubResponse"] == {"id": 88}
    assert data["crawlerUrls"][0]["validationErrors"] == [{"field": "url"}]
    assert data["toolEdits"]["crawler-tool"]["baseRevision"] == "rev-1"
    assert data["toolEdits"]["crawler-tool"]["fieldStatuses"] == {"title": "accepted"}
    assert data["toolEdits"]["crawler-tool"]["reviewStatus"] == "open"
    assert data["toolEdits"]["crawler-tool"]["toolhubResponse"] == {"message": "bad"}
    assert data["toolEdits"]["crawler-tool"]["validationErrors"] == [{"field": "title"}]
    assert data["toolNew"]["crawler-tool"]["officialName"] == "crawler-tool-official"
    assert data["toolNew"]["crawler-tool"]["visibility"] == "public"
    assert data["toolNew"]["crawler-tool"]["source"] == "local"
    assert data["toolNew"]["crawler-tool"]["reviewStatus"] == "pending"
    assert data["toolNew"]["crawler-tool"]["toolhubResponse"] == {"id": 99}
    assert data["toolNew"]["crawler-tool"]["validationErrors"] == [{"field": "url"}]
    assert client.get("/v1/search/tools/?q=crawler").get_json()["count"] == 0
    assert client.get("/toolinfo.json").get_json() == []
    with db.session_scope() as s:
        row = s.execute(select(ToolRecord).where(ToolRecord.tool_name == "crawler-tool")).scalar_one()
        row.review_status = "approved"
    assert client.get("/v1/search/tools/?q=crawler").get_json()["count"] == 1
    assert client.get("/toolinfo.json").get_json()[0]["name"] == "toolhub-evolved-crawler-tool"


def test_local_overlays_cannot_replace_canonical_tool_identity(client):
    uid = add_user()
    sign_in(client, uid)
    patch = {
        "live-tool": {
            "name": "local-shadow",
            "origin": "api",
            "description": "local note",
            "source": "local",
            "createdByUserId": 999,
            "deletedAt": "2026-07-26T12:00:00Z",
        }
    }
    assert put_overlay(client, "toolEdits", patch).status_code == 200
    data = client.get("/v1/overlay/").get_json()["toolEdits"]["live-tool"]
    assert data["description"] == "local note"
    assert data["source"] == "local"
    assert "name" not in data
    assert "origin" not in data
    assert "createdByUserId" not in data
    assert "deletedAt" not in data
    with db.session_scope() as s:
        stored = s.query(ToolOverlay).filter_by(tool_name="live-tool").one()
        assert stored.patch == {"description": "local note"}


def test_non_reviewer_public_tool_records_require_review_and_preserve_approved_state(client):
    uid_a = add_user("Ada", "1")
    uid_b = add_user("Grace", "2")
    sign_in(client, uid_a)
    public_tool = {
        "title": "Public Draft",
        "description": "Needs review",
        "url": "https://draft.example",
        "visibility": "public",
        "reviewStatus": "approved",
    }
    assert put_overlay(client, "toolNew", {"public-draft": public_tool}).status_code == 200
    own = client.get("/v1/overlay/").get_json()["toolNew"]["public-draft"]
    assert own["reviewStatus"] == "pending"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 0
    with db.session_scope() as s:
        row = s.query(ToolRecord).filter_by(tool_name="public-draft").one()
        row.review_status = "approved"
    assert put_overlay(client, "toolNew", {"public-draft": public_tool}).status_code == 200
    own = client.get("/v1/overlay/").get_json()["toolNew"]["public-draft"]
    assert own["reviewStatus"] == "approved"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 1

    sign_in(client, uid_b)
    public_to_others = client.get("/v1/overlay/").get_json()["toolNew"]["public-draft"]
    assert public_to_others["reviewStatus"] == "approved"
    assert public_to_others["source"] == "local"


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
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada",
                toolhub_username="Ada",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
            )
        )
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
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
    assert exported["authorClaims"][0]["toolName"] == "ada-tool"
    assert exported["authorKeys"][0]["keyId"] == "k1"
    resp = client.delete("/v1/user/evolved-data/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json()["deleted"]["favorites"] == 1
    assert resp.get_json()["deleted"]["authorClaims"] == 1
    assert resp.get_json()["deleted"]["authorKeys"] == 1
    with db.session_scope() as s:
        assert s.query(CrawlerUrl).count() == 0
        assert s.query(ToolList).count() == 0
        assert s.query(ToolAuthorClaim).count() == 0
        assert s.query(ToolAuthorKey).count() == 0


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
                review_status="approved",
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
                review_status="approved",
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
    assert signals["source"] == "local"
    assert signals["syncStatus"] == "evolved_real"
    assert signals["syncLabel"] == "Evolved data"
    assert signals["thanks"]["count"] == 1
    assert signals["thanks"]["userThanked"] is True
    assert signals["thanks"]["syncLabel"] == "Evolved data"
    assert signals["usage30d"]["count"] == 1
    assert signals["usage30d"]["syncLabel"] == "Evolved data"
    assert signals["health"]["status"] == "unknown"
    assert client.delete("/v1/tools/alpha/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.get("/v1/tools/alpha/signals/").get_json()["thanks"]["count"] == 0

    health = client.put(
        "/v1/tools/alpha/health-target/",
        json={"url": "https://alpha.example/healthz"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert health.status_code == 200
    assert health.get_json()["healthTarget"]["reviewStatus"] == "pending"
    assert health.get_json()["healthTarget"]["syncLabel"] == "Evolved data"
    assert client.get("/v1/tools/alpha/signals/").get_json()["health"]["status"] == "unknown"
    with db.session_scope() as s:
        target = s.query(ToolHealthTarget).one()
        target.review_status = "approved"
        target.last_status = "healthy"
        target.last_checked_at = utcnow()
    health_signals = client.get("/v1/tools/alpha/signals/").get_json()["health"]
    assert health_signals["status"] == "healthy"
    assert health_signals["targetUrl"] == "https://alpha.example/healthz"
    assert health_signals["reviewStatus"] == "approved"
    assert health_signals["syncLabel"] == "Evolved data"

    media_payload = {"url": "https://img.example/shot.png", "license": "CC-BY-SA-4.0", "source": "Maintainer upload"}
    media = client.post("/v1/tools/alpha/media/", json=media_payload, headers={"X-CSRF-Token": "tok"})
    assert media.status_code == 200
    assert media.get_json()["media"]["reviewStatus"] == "pending"
    assert media.get_json()["media"]["syncLabel"] == "Evolved data"
    assert client.get("/v1/tools/alpha/media/").get_json()["count"] == 0  # pending media is not public
    with db.session_scope() as s:
        row = s.query(ToolMedia).one()
        row.review_status = "approved"
    media_list = client.get("/v1/tools/alpha/media/").get_json()
    assert media_list["count"] == 1
    assert media_list["results"][0]["syncLabel"] == "Evolved data"
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
    with db.session_scope() as s:
        s.add(ToolThanks(tool_name="legacy-thanks", user_id=uid, active=False))
    assert client.post("/v1/tools/legacy-thanks/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    with db.session_scope() as s:
        thanks = s.query(ToolThanks).filter_by(tool_name="legacy-thanks").one()
        assert thanks.created_by_user_id == uid
        assert thanks.review_status == "approved"

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
        assert target.review_status == "pending"
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


def test_public_evolved_data_moderation_lifecycle(client):
    uid = add_user("Ada", "1")
    sign_in(client, uid)
    public_tool = {"title": "Public Draft", "description": "Needs review", "url": "https://draft.example"}
    assert put_overlay(client, "toolNew", {"public-draft": {**public_tool, "visibility": "public"}}).status_code == 200
    assert (
        client.put(
            "/v1/tools/public-draft/health-target/",
            json={"url": "https://draft.example/healthz"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    media = client.post(
        "/v1/tools/public-draft/media/",
        json={"url": "https://img.example/draft.png", "license": "CC0", "source": "Maintainer"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert media.status_code == 200
    assert client.post("/v1/tools/public-draft/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    with db.session_scope() as s:
        tool_row = s.query(ToolRecord).filter_by(tool_name="public-draft").one()
        health_row = s.query(ToolHealthTarget).one()
        media_row = s.query(ToolMedia).filter_by(tool_name="public-draft").one()
        thanks_row = s.query(ToolThanks).one()
        health_row.last_status = "healthy"
        health_row.last_checked_at = utcnow()
        thanks_row.review_status = "pending"
        deleted_media = ToolMedia(
            tool_name="public-draft",
            user_id=uid,
            created_by_user_id=uid,
            url="https://img.example/deleted.png",
            license="CC0",
            source="Maintainer",
            deleted_at=utcnow(),
        )
        private_record = ToolRecord(
            tool_name="private-draft",
            user_id=uid,
            created_by_user_id=uid,
            record={**public_tool, "title": "Private Draft"},
            visibility="private",
            review_status="pending",
        )
        s.add_all([deleted_media, private_record])
        s.flush()
        ids = {
            "tool": tool_row.id,
            "health": health_row.id,
            "media": media_row.id,
            "thanks": thanks_row.id,
            "deletedMedia": deleted_media.id,
            "privateTool": private_record.id,
        }

    assert client.get("/v1/moderation/public-data/").status_code == 403
    reviewer_id = add_user("Reviewer", "2", role=authz.ROLE_REVIEWER)
    sign_in(client, reviewer_id)
    headers = {"X-CSRF-Token": "tok"}
    reviewer_tool = {
        "title": "Reviewer Tool",
        "description": "Reviewer-approved local record",
        "url": "https://reviewer.example",
        "visibility": "public",
        "reviewStatus": "approved",
    }
    assert put_overlay(client, "toolNew", {"reviewer-tool": reviewer_tool}).status_code == 200
    assert client.get("/v1/search/tools/?q=reviewer").get_json()["count"] == 1
    queue = client.get("/v1/moderation/public-data/").get_json()
    assert queue["source"] == "local"
    assert queue["syncStatus"] == "evolved_real"
    assert queue["syncLabel"] == "Evolved data"
    assert queue["count"] == 4
    assert {item["kind"] for item in queue["results"]} == {"tool-records", "health-targets", "media", "thanks"}
    assert {item["data"]["syncLabel"] for item in queue["results"]} == {"Evolved data"}

    assert (
        client.put(
            "/v1/moderation/public-data/unknown/1/", json={"reviewStatus": "approved"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/tool-records/{ids['tool']}/", data="not-json", headers=headers
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/tool-records/{ids['tool']}/",
            json={"reviewStatus": "open"},
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/v1/moderation/public-data/tool-records/999/", json={"reviewStatus": "approved"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/tool-records/{ids['privateTool']}/",
            json={"reviewStatus": "approved"},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/media/{ids['deletedMedia']}/",
            json={"reviewStatus": "approved"},
            headers=headers,
        ).status_code
        == 404
    )

    pending = client.put(
        f"/v1/moderation/public-data/tool-records/{ids['tool']}/",
        json={"reviewStatus": "pending"},
        headers=headers,
    )
    assert pending.status_code == 200
    assert pending.get_json()["item"]["data"]["reviewStatus"] == "pending"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 0

    approve_tool = client.put(
        f"/v1/moderation/public-data/tool-records/{ids['tool']}/",
        json={"reviewStatus": "approved"},
        headers=headers,
    )
    assert approve_tool.status_code == 200
    assert approve_tool.get_json()["item"]["data"]["source"] == "local"
    assert approve_tool.get_json()["item"]["data"]["syncLabel"] == "Evolved data"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 1
    assert client.get("/toolinfo.json").get_json()[0]["name"] == "toolhub-evolved-public-draft"

    assert (
        client.put(
            f"/v1/moderation/public-data/health-targets/{ids['health']}/",
            json={"reviewStatus": "approved"},
            headers=headers,
        ).status_code
        == 200
    )
    health = client.get("/v1/tools/public-draft/signals/").get_json()["health"]
    assert health["status"] == "healthy"
    assert health["syncLabel"] == "Evolved data"

    assert (
        client.put(
            f"/v1/moderation/public-data/media/{ids['media']}/",
            json={"review_status": "approved"},
            headers=headers,
        ).status_code
        == 200
    )
    media_list = client.get("/v1/tools/public-draft/media/").get_json()
    assert media_list["count"] == 1
    assert media_list["results"][0]["syncStatus"] == "evolved_real"

    assert (
        client.put(
            f"/v1/moderation/public-data/thanks/{ids['thanks']}/",
            json={"reviewStatus": "rejected"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/v1/tools/public-draft/signals/").get_json()["thanks"]["count"] == 0
    sign_in(client, uid)
    assert client.post("/v1/tools/public-draft/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.get("/v1/tools/public-draft/signals/").get_json()["thanks"]["count"] == 0
    with db.session_scope() as s:
        assert s.get(ToolThanks, ids["thanks"]).review_status == "rejected"
        activity = s.query(ActivityRow).filter(ActivityRow.action == "public-data-reviewed").all()
        assert len(activity) == 10
        assert {row.kind for row in activity} == {"revisions", "auditlogs"}
        assert len({(row.object_type, row.object_key) for row in activity}) == 4
        assert {row.payload["reviewStatus"] for row in activity if row.object_type == "tool-records"} == {
            "pending",
            "approved",
        }


class FakeResp:
    def __init__(self, payload, status=200, headers=None, content=None):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)
        self.ok = status < 400
        self.headers = headers or {"content-type": "application/json"}
        self.content = content if content is not None else dumps(payload).encode("utf-8")

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


def test_public_api_url_stays_inside_the_api_tree():
    assert toolhub._public_api_url("/api/tools/").endswith("/api/tools/")
    for path in ("/o/token/", "/api/../o/token/", "api/tools/../../o/token/"):
        with pytest.raises(ValueError, match="anonymous reads"):
            toolhub._public_api_url(path)


def stored_grant(uid):
    """Return the decrypted (access, refresh) pair persisted for one user."""
    with db.session_scope() as s:
        row = s.get(ToolhubToken, uid)
        refresh = token_crypto.decrypt(row.refresh_token) if row.refresh_token else None
        return token_crypto.decrypt(row.access_token), refresh


def configure_oauth(monkeypatch):
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_SECRET", "csec")
    # The callback URL is only derived from request headers in development, so
    # tests that drive the flow have to say which of the two modes they are in.
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")


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


def test_toolhub_public_api_get_uses_shared_cache(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResp({"results": [{"name": "cached"}]}, headers={"content-type": "application/json", "etag": "e1"})

    monkeypatch.setattr(toolhub.requests, "get", fake_get)
    assert toolhub.public_api_get("/api/search/tools/", params={"author__term": "Ada"}) == {
        "results": [{"name": "cached"}]
    }
    assert calls[0][0] == "https://toolhub.example/api/search/tools/?author__term=Ada"
    assert calls[0][1]["headers"]["Accept"] == "application/json"
    assert toolhub.public_api_get("/api/search/tools/", params={"author__term": "Ada"}) == {
        "results": [{"name": "cached"}]
    }
    assert len(calls) == 1


def test_toolhub_public_api_get_rejects_non_api_paths():
    with pytest.raises(ValueError, match="/api/"):
        toolhub.public_api_get("/oauth/login")


def test_toolhub_public_api_get_leaves_noncacheable_success_uncached(client, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResp({"message": "unchanged"}, 304)

    monkeypatch.setattr(toolhub.requests, "get", fake_get)
    assert toolhub.public_api_get("/api/schema/") == {"message": "unchanged"}
    assert toolhub.public_api_get("/api/schema/") == {"message": "unchanged"}
    assert len(calls) == 2


def test_toolhub_public_api_get_raises_upstream_error(client, monkeypatch):
    monkeypatch.setattr(toolhub.requests, "get", lambda *a, **k: FakeResp({"message": "bad"}, 503))
    with pytest.raises(toolhub.ToolhubAPIError) as exc:
        toolhub.public_api_get("/api/search/tools/")
    assert exc.value.status_code == 503
    assert exc.value.payload == {"message": "bad"}


def test_recent_owner_resolver_fetches_once_then_uses_toolsdb_cache(client, monkeypatch):
    calls = []

    def fake_public_api_get(path, **_kwargs):
        calls.append(path)
        return {"name": "my-tool", "author": [{"name": "Ada Maintainer"}]}

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    first = client.get("/v1/recent/owners/?tool=my-tool&tool=my-tool").get_json()
    second = client.get("/v1/recent/owners/?tools=my-tool").get_json()

    assert first["owners"] == {"my-tool": "Ada Maintainer"}
    assert first["meta"]["my-tool"]["cached"] is False
    assert second["owners"] == {"my-tool": "Ada Maintainer"}
    assert second["meta"]["my-tool"]["cached"] is True
    assert calls == ["/api/tools/my-tool/"]
    with db.session_scope() as s:
        row = s.get(ToolOwnerCache, "my-tool")
        assert row.owner == "Ada Maintainer"
        assert row.source == "toolhub_detail"


def test_owner_cache_purges_only_rows_past_their_stale_window(client):
    now = utcnow()
    with db.session_scope() as s:
        s.add(ToolOwnerCache(tool_name="live", owner="Ada", fetched_at=now, expires_at=now, stale_until=now + timedelta(days=1)))
        s.add(
            ToolOwnerCache(
                tool_name="dead", owner="", fetched_at=now, expires_at=now, stale_until=now - timedelta(days=1)
            )
        )
    assert recent_owners.purge_expired() == 1
    with db.session_scope() as s:
        assert s.get(ToolOwnerCache, "live") is not None
        assert s.get(ToolOwnerCache, "dead") is None
    assert recent_owners.purge_expired() == 0  # idempotent


def test_unresolved_owner_rows_expire_far_sooner_than_resolved_ones(client, monkeypatch):
    monkeypatch.setattr(toolhub, "public_api_get", lambda path, **_k: {"name": path, "author": []})
    client.get("/v1/recent/owners/?tool=nobody")  # resolves to no owner → negative entry
    with db.session_scope() as s:
        row = s.get(ToolOwnerCache, "nobody")
        # Junk names are the ones an attacker can mint freely, so they must not
        # occupy the table for the full positive-entry week.
        assert (row.stale_until - row.fetched_at).total_seconds() <= (
            recent_owners.OWNER_NEGATIVE_FRESH_SECONDS + recent_owners.OWNER_NEGATIVE_STALE_SECONDS
        )


def test_recent_owners_defers_names_past_the_fetch_budget(client, monkeypatch):
    calls = []

    def fake_public_api_get(path, **_kwargs):
        calls.append(path)
        return {"name": path, "author": [{"name": "Ada"}]}

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    cold = recent_owners.OWNER_FETCH_BUDGET + 6
    names = "&".join(f"tool=cold-{i}" for i in range(cold))
    data = client.get(f"/v1/recent/owners/?{names}").get_json()

    assert len(calls) == recent_owners.OWNER_FETCH_BUDGET  # one request cannot fan out further
    deferred = [n for n, m in data["meta"].items() if m["source"] == recent_owners.SOURCE_DEFERRED]
    assert len(deferred) == cold - recent_owners.OWNER_FETCH_BUDGET
    assert all(data["owners"][name] == "" for name in deferred)
    with db.session_scope() as s:
        # Deferred means unknown, not known-empty: nothing may be cached for them,
        # or the next request would treat the blank as a resolved answer.
        assert all(s.get(ToolOwnerCache, name) is None for name in deferred)


def test_recent_owners_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_a, **_k: {"name": "t", "author": []})
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    for _ in range(security.READ_LIMIT):
        assert client.get("/v1/recent/owners/?tool=warm").status_code == 200
    resp = client.get("/v1/recent/owners/?tool=warm")
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "rate limit exceeded"
    clock["t"] += security.WRITE_WINDOW_SECONDS + 1  # window rolls over
    assert client.get("/v1/recent/owners/?tool=warm").status_code == 200


def test_resolve_owners_without_a_budget_is_unlimited(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        toolhub, "public_api_get", lambda path, **_k: calls.append(path) or {"name": path, "author": []}
    )
    # The scheduled prewarm job is trusted and passes no budget.
    recent_owners.resolve_owners([f"job-{i}" for i in range(recent_owners.OWNER_FETCH_BUDGET + 3)])
    assert len(calls) == recent_owners.OWNER_FETCH_BUDGET + 3


def test_recent_owner_resolver_returns_stale_owner_when_toolhub_fails(client, monkeypatch):
    with db.session_scope() as s:
        now = utcnow()
        s.add(
            ToolOwnerCache(
                tool_name="stale-tool",
                owner="Cached Owner",
                fetched_at=now - timedelta(days=2),
                expires_at=now - timedelta(seconds=1),
                stale_until=now + timedelta(days=1),
            )
        )

    def failing_public_api_get(_path, **_kwargs):
        raise toolhub.ToolhubAPIError(503, {"message": "down"})

    monkeypatch.setattr(toolhub, "public_api_get", failing_public_api_get)
    data = client.get("/v1/recent/owners/?tool=stale-tool").get_json()

    assert data["owners"] == {"stale-tool": "Cached Owner"}
    assert data["meta"]["stale-tool"]["cached"] is True
    assert data["meta"]["stale-tool"]["stale"] is True
    with db.session_scope() as s:
        assert "Toolhub API returned 503" in s.get(ToolOwnerCache, "stale-tool").last_error


def test_recent_owner_resolver_cleans_bounds_and_negative_caches_failures(client, monkeypatch):
    calls = []

    def failing_public_api_get(path, **_kwargs):
        calls.append(path)
        raise toolhub.ToolhubAPIError(404, {"message": "missing"})

    monkeypatch.setattr(toolhub, "public_api_get", failing_public_api_get)
    names = "&".join(f"tool=tool-{i}" for i in range(recent_owners.OWNER_MAX_NAMES + 5))
    data = client.get(f"/v1/recent/owners/?tool=&tool=tool-0&{names}").get_json()

    assert data["count"] == recent_owners.OWNER_MAX_NAMES
    assert data["owners"]["tool-0"] == ""
    # The name list is still bounded at OWNER_MAX_NAMES, but only the first
    # OWNER_FETCH_BUDGET cold names may go upstream in one request.
    assert len(calls) == recent_owners.OWNER_FETCH_BUDGET
    with db.session_scope() as s:
        row = s.get(ToolOwnerCache, "tool-0")
        assert row.owner == ""
        assert row.last_error
        assert row.expires_at > utcnow()


def test_recent_owner_record_parser_prefers_author_display_name():
    assert recent_owners.owner_from_tool_record({"author": [{"name": "Display", "developer_username": "dev"}]}) == "Display"
    assert recent_owners.owner_from_tool_record({"author": [{"developer_username": "dev"}]}) == "dev"
    assert recent_owners.owner_from_tool_record({"author": "Plain Author"}) == "Plain Author"
    assert recent_owners.owner_from_tool_record({"created_by": {"username": "creator"}}) == "creator"
    assert recent_owners.owner_from_tool_record({}) == ""


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
    assert stored_grant(uid) == ("new", "rt2")
    toolhub.save_grant(uid, {"access_token": "third"})
    assert stored_grant(uid) == ("third", "rt2")
    uid_no_rotate = add_user(wm_sub="refresh-no-rotate")
    toolhub.save_grant(uid_no_rotate, {"access_token": "old2", "refresh_token": "keep", "expires_in": -120})
    toolhub.api_request(uid_no_rotate, "POST", "/api/tools/", json={"name": "x"})
    assert stored_grant(uid_no_rotate) == ("new-no-rotate", "keep")


def test_stored_grants_are_encrypted_at_rest(client):
    uid = add_user(wm_sub="sealed")
    toolhub.save_grant(uid, {"access_token": "secret-access", "refresh_token": "secret-refresh"})
    with db.session_scope() as s:
        row = s.get(ToolhubToken, uid)
        assert row.access_token.startswith(token_crypto.PREFIX)
        assert "secret-access" not in row.access_token  # ciphertext, not an encoding
        assert "secret-refresh" not in row.refresh_token
    assert stored_grant(uid) == ("secret-access", "secret-refresh")


def test_legacy_plaintext_grants_are_readable_and_resealed_on_read(client, monkeypatch):
    uid = add_user(wm_sub="legacy")
    with db.session_scope() as s:  # a row written before encryption existed
        s.add(ToolhubToken(user_id=uid, access_token="plain-access", refresh_token="plain-refresh"))
    monkeypatch.setattr(toolhub.requests, "request", lambda *_a, **kw: FakeResp({"ok": True}))
    body, status = toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    assert (body, status) == ({"ok": True}, 200)
    with db.session_scope() as s:
        assert s.get(ToolhubToken, uid).access_token.startswith(token_crypto.PREFIX)  # migrated in place
    assert stored_grant(uid) == ("plain-access", "plain-refresh")


def test_unreadable_grant_is_dropped_and_forces_reauth(client, monkeypatch):
    uid = add_user(wm_sub="rotated")
    toolhub.save_grant(uid, {"access_token": "a", "refresh_token": "r"})
    token_crypto.configure("a-completely-different-session-secret")  # simulate key rotation
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    with db.session_scope() as s:
        assert s.get(ToolhubToken, uid) is None  # fail closed: unreadable grant forgotten


def test_token_crypto_requires_configuration(monkeypatch):
    monkeypatch.setattr(token_crypto, "_fernet", None)
    with pytest.raises(RuntimeError, match="configure"):
        token_crypto.encrypt("x")


def test_token_key_env_overrides_the_session_secret(monkeypatch):
    monkeypatch.setenv("TOOLHUB_TOKEN_KEY", "independent-token-key")
    token_crypto.configure("session-secret-a")
    sealed = token_crypto.encrypt("grant")
    token_crypto.configure("session-secret-b")  # session key rotated…
    assert token_crypto.decrypt(sealed) == "grant"  # …grant survives


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
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        api_cache.CacheableResponse(200, "application/json", b'{"name":"my-tool","title":"old"}'),
    )
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        api_cache.CacheableResponse(200, "application/json", b'{"results":[]}'),
    )
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
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 0
        claim = s.query(ToolAuthorClaim).filter_by(tool_name="my-tool", author_name="Ada").one()
        assert claim.toolhub_username == "Ada"
        assert claim.verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert claim.verification_method == sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS


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


def test_official_bridge_respects_evolved_policy_before_toolhub_call(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    calls = []
    monkeypatch.setattr(authz, "can", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(toolhub.requests, "request", lambda *args, **kwargs: calls.append((args, kwargs)))
    resp = client.post("/v1/toolhub/tools/", json={"name": "x"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 403
    assert calls == []


def test_official_delete_normalizes_204(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({}, 204))
    resp = client.delete("/v1/toolhub/user/favorites/my-tool/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ---- official-first write lifecycle ----------------------------------------


TOOL_WRITE_PAYLOAD = {
    "name": "my-tool",
    "title": "My Tool",
    "description": "Useful tool",
    "url": "https://example.org/tool",
    "repository": "https://example.org/repo",
    "license": "GPL-3.0-or-later",
    "tool_type": "web app",
    "keywords": ["demo", 7],
    "for_wikis": ["en.wikipedia.org"],
    "available_ui_languages": ["en"],
    "deprecated": False,
    "experimental": True,
}


def test_write_lifecycle_validation_helpers_normalize_toolhub_errors():
    assert _message_from_payload({"detail": "  explain it  "}, "fallback") == "explain it"
    assert _message_from_payload({"message": ""}, "fallback") == "fallback"
    assert _message_from_payload("plain", "fallback") == "fallback"
    assert _string_list("not-list") == []
    assert _validation_errors(["plain", {"field": "url"}]) == [{"message": "plain"}, {"field": "url"}]
    assert _validation_errors({"errors": ["bad"]}) == [{"message": "bad"}]
    assert _validation_errors({"title": ["too short"], "url": "bad", "message": "ignored"}) == [
        {"field": "title", "messages": ["too short"]},
        {"field": "url", "messages": ["bad"]},
    ]
    assert _validation_errors("plain") == []
    assert _official_annotation_payload({"audiences": [], "tasks": [], "toolType": None, "icon": None}) == {
        "audiences": [],
        "tasks": [],
        "comment": "Annotated from Toolhub Evolved",
    }
    assert _official_id("not-dict", 5) == 5
    assert v1_api._create_toolinfo_url({}) == (None, None)
    assert v1_api._create_toolinfo_url({"toolinfoUrl": 7}) == (None, None)
    assert v1_api._matching_toolinfo_item("bad", "my-tool") is None
    assert v1_api._matching_toolinfo_item([{"name": "other"}, None, {"name": "my-tool"}], "my-tool") == {
        "name": "my-tool"
    }
    assert v1_api._matching_toolinfo_item([{"name": "other"}], "my-tool") is None
    merged, enriched = v1_api._merge_toolinfo_fields(
        {
            "repository": "https://manual.example/repo",
            "license": "Apache-2.0",
            "toolType": "web app",
            "keywords": ["manual"],
            "forWikis": ["en.wikipedia.org"],
            "uiLanguages": ["en"],
            "deprecated": True,
            "experimental": True,
        },
        {
            "repository": "https://toolinfo.example/repo",
            "license": "MIT",
            "toolType": "bot",
            "keywords": ["crawler"],
            "forWikis": ["commons.wikimedia.org"],
            "uiLanguages": ["fr"],
            "deprecated": True,
            "experimental": True,
        },
    )
    assert enriched == []
    assert merged["repository"] == "https://manual.example/repo"


def test_create_toolinfo_fetch_helpers_reuse_crawler_module(monkeypatch):
    import crawl

    monkeypatch.setattr(crawl, "_fetch_json", lambda _session, url: {"url": url})
    assert v1_api._fetch_toolinfo_json_once("https://toolinfo.example/toolinfo.json") == {
        "url": "https://toolinfo.example/toolinfo.json"
    }


def test_create_toolinfo_enrichment_handles_invalid_matching_item(monkeypatch):
    fields = {
        "title": "Manual title",
        "description": "Manual description",
        "url": "https://manual.example/tool",
        "repository": None,
        "license": None,
        "toolType": None,
        "keywords": [],
        "forWikis": [],
        "uiLanguages": [],
        "deprecated": False,
        "experimental": False,
        "origin": "api",
    }
    monkeypatch.setattr(
        v1_api,
        "_fetch_toolinfo_json_once",
        lambda _url: {"name": "my-tool", "title": "Incomplete", "url": "https://toolinfo.example/tool"},
    )
    merged, item, result = v1_api._create_toolinfo_enrichment(
        fields,
        "my-tool",
        "https://toolinfo.example/toolinfo.json",
    )
    assert merged == fields
    assert item["name"] == "my-tool"
    assert result == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": False,
        "matched": True,
        "enrichedFields": [],
        "lastError": "my-tool: toolinfo item is missing name, title, description or url",
    }


def test_record_create_toolinfo_evidence_handles_no_item_and_provider_failure(client, monkeypatch):
    uid = add_user(username="schiste")
    with db.session_scope() as s:
        user = s.get(User, uid)
        v1_api._record_create_toolinfo_evidence(
            s,
            user,
            "https://toolinfo.example/no-item.json",
            None,
            {"url": "https://toolinfo.example/no-item.json", "ok": True},
        )

    def fail_verify(*_args, **_kwargs):
        msg = "verification backend failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(v1_api.SIGNED_TOOLINFO_PROVIDER, "verify", fail_verify)
    with db.session_scope() as s:
        user = s.get(User, uid)
        v1_api._record_create_toolinfo_evidence(
            s,
            user,
            "https://toolinfo.example/provider-failure.json",
            {"name": "my-tool"},
            {"url": "https://toolinfo.example/provider-failure.json", "ok": True},
        )
    with db.session_scope() as s:
        assert s.query(CrawlerUrl).count() == 2


def test_write_tool_create_fetches_toolinfo_and_records_evidence(client, monkeypatch):
    uid = add_user(username="schiste")
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    toolinfo_item = {
        "name": "my-tool",
        "title": "Toolinfo title",
        "description": "Toolinfo description",
        "url": "https://toolinfo.example/tool",
        "repository": "https://toolinfo.example/repo",
        "license": "MIT",
        "tool_type": "bot",
        "keywords": ["crawler", "evolved"],
        "for_wikis": ["commons.wikimedia.org"],
        "available_ui_languages": ["fr"],
        "deprecated": True,
        "experimental": False,
    }
    official_calls = []
    verify_calls = []

    monkeypatch.setattr(v1_api, "_fetch_toolinfo_json_once", lambda url: {**toolinfo_item, "url": url})
    monkeypatch.setattr(
        v1_api.SIGNED_TOOLINFO_PROVIDER,
        "verify",
        lambda s, user, *, toolinfo, evidence_url: verify_calls.append((user.username, toolinfo["name"], evidence_url)),
    )

    def fake_request(method, url, **kwargs):
        official_calls.append((method, url, kwargs.get("json")))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    payload = {
        "name": "my-tool",
        "title": "Manual title",
        "description": "Manual description",
        "url": "https://manual.example/tool",
        "keywords": [],
        "for_wikis": [],
        "available_ui_languages": [],
        "deprecated": False,
        "experimental": False,
        "toolinfo_url": "https://toolinfo.example/toolinfo.json",
    }
    resp = client.post("/v1/write/tools/", json=payload, headers={"X-CSRF-Token": "tok"})
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["crawlerFetch"] == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": True,
        "matched": True,
        "enrichedFields": [
            "repository",
            "license",
            "toolType",
            "keywords",
            "forWikis",
            "uiLanguages",
            "deprecated",
        ],
    }
    assert official_calls[0][2] == {
        "name": "my-tool",
        "title": "Manual title",
        "description": "Manual description",
        "url": "https://manual.example/tool",
        "repository": "https://toolinfo.example/repo",
        "license": "MIT",
        "tool_type": "bot",
        "keywords": ["crawler", "evolved"],
        "for_wikis": ["commons.wikimedia.org"],
        "available_ui_languages": ["fr"],
        "deprecated": True,
        "experimental": False,
        "comment": "Published from Toolhub Evolved",
    }
    assert verify_calls == [("schiste", "my-tool", "https://toolinfo.example/toolinfo.json")]
    with db.session_scope() as s:
        crawler = s.execute(
            select(CrawlerUrl).where(CrawlerUrl.url == "https://toolinfo.example/toolinfo.json")
        ).scalar_one()
        assert crawler.sync_status == "evolved_real"
        assert crawler.last_error is None
        activity = s.execute(select(ActivityRow).where(ActivityRow.kind == "revisions")).scalar_one()
        assert activity.payload["crawlerFetch"]["ok"] is True


def test_write_tool_create_toolinfo_fetch_failure_keeps_official_create(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    official_calls = []

    def fail_fetch(_url):
        msg = "temporary crawler outage"
        raise ValueError(msg)

    def fake_request(method, url, **kwargs):
        official_calls.append(kwargs.get("json"))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(v1_api, "_fetch_toolinfo_json_once", fail_fetch)
    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    resp = client.post(
        "/v1/write/tools/",
        json={**TOOL_WRITE_PAYLOAD, "toolinfo_url": "https://toolinfo.example/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["crawlerFetch"] == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": False,
        "matched": False,
        "enrichedFields": [],
        "lastError": "temporary crawler outage",
    }
    assert "toolinfo_url" not in official_calls[0]
    with db.session_scope() as s:
        crawler = s.execute(
            select(CrawlerUrl).where(CrawlerUrl.url == "https://toolinfo.example/toolinfo.json")
        ).scalar_one()
        assert crawler.sync_status == "sync_error"
        assert crawler.last_error == "temporary crawler outage"


def test_write_tool_create_toolinfo_no_match_stays_in_local_fallback_response(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(v1_api, "_fetch_toolinfo_json_once", lambda _url: [{"name": "other-tool"}])
    monkeypatch.setattr(toolhub.requests, "request", lambda *_args, **_kwargs: FakeResp({"message": "bad"}, 400))
    resp = client.post(
        "/v1/write/tools/",
        json={**TOOL_WRITE_PAYLOAD, "toolinfo_url": "https://toolinfo.example/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    data = resp.get_json()
    assert resp.status_code == 202
    assert data["crawlerFetch"] == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": False,
        "matched": False,
        "enrichedFields": [],
        "lastError": "my-tool: no matching item found in toolinfo",
    }


def test_write_tool_create_success_clears_local_state_and_emits_activity(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(
            ToolRecord(
                tool_name="my-tool",
                user_id=uid,
                created_by_user_id=uid,
                record={"title": "Draft", "description": "d", "url": "https://draft.example"},
            )
        )
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="my-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch={"title": "Local"},
            )
        )
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["result"] == "official"
    assert data["syncStatus"] == "official"
    assert calls == [
        (
            "POST",
            "https://toolhub.wikimedia.org/api/tools/",
            {
                "name": "my-tool",
                "title": "My Tool",
                "description": "Useful tool",
                "url": "https://example.org/tool",
                "repository": "https://example.org/repo",
                "license": "GPL-3.0-or-later",
                "tool_type": "web app",
                "keywords": ["demo", "7"],
                "for_wikis": ["en.wikipedia.org"],
                "available_ui_languages": ["en"],
                "deprecated": False,
                "experimental": True,
                "comment": "Published from Toolhub Evolved",
            },
        )
    ]
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0
        assert s.query(ToolOverlay).count() == 0
        activity = s.execute(select(ActivityRow).where(ActivityRow.kind == "revisions")).scalar_one()
        assert activity.object_type == "tool"
        assert activity.object_key == "my-tool"
        assert activity.action == "created"
        assert activity.official_status == "official"
        assert activity.last_synced_at is not None
        assert activity.row["officialStatus"] == "official"


def test_write_tool_rejection_stores_overlay_fallback_with_validation_errors(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"message": "bad payload", "title": ["too short"]}, 400),
    )
    payload = {**TOOL_WRITE_PAYLOAD, "name": "ignored", "title": "New title"}
    resp = client.put("/v1/write/tools/live-tool/", json=payload, headers={"X-CSRF-Token": "tok"})
    data = resp.get_json()
    assert resp.status_code == 202
    assert data["result"] == "local_fallback"
    assert data["lastError"] == "bad payload"
    assert data["validationErrors"] == [{"field": "title", "messages": ["too short"]}]
    assert data["local"]["title"] == "New title"
    with db.session_scope() as s:
        overlay = s.execute(select(ToolOverlay).where(ToolOverlay.tool_name == "live-tool")).scalar_one()
        assert overlay.kind == "edits"
        assert overlay.patch["title"] == "New title"
        assert overlay.sync_status == "local_fallback"
        assert overlay.last_toolhub_response == {"message": "bad payload", "title": ["too short"]}
        assert overlay.validation_errors == [{"field": "title", "messages": ["too short"]}]
        activity = s.execute(select(ActivityRow).where(ActivityRow.kind == "auditlogs")).scalar_one()
        assert activity.official_status == "local_fallback"
        assert activity.last_error == "bad payload"


def test_write_tool_rejection_without_local_permission_returns_official_error(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(
        authz,
        "can",
        lambda _user, action, _resource=None: action == authz.ACTION_TOOLHUB_WRITE,
    )
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "denied"}, 403))
    resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 403
    assert resp.get_json()["lastError"] == "denied"
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0


def test_write_lifecycle_requires_toolhub_grant_before_fallback(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 401
    assert resp.get_json()["reauth"] is True
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0


def test_write_annotations_and_crawler_failures_store_local_fallbacks(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})

    def fake_request(method, url, **kwargs):
        if url.endswith("/api/crawler/urls/"):
            raise toolhub.requests.ConnectionError("down")
        assert method == "PUT"
        assert kwargs["json"]["tool_type"] == "web app"
        return FakeResp({"errors": [{"field": "audiences", "message": "bad"}]}, 400)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    resp = client.put(
        "/v1/write/tools/my-tool/annotations/",
        json={"audiences": ["editors"], "tasks": ["patrol"], "tool_type": "web app"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 202
    assert resp.get_json()["validationErrors"] == [{"field": "audiences", "message": "bad"}]
    resp = client.post(
        "/v1/write/crawler/urls/",
        json={"url": "https://example.org/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 202
    assert resp.get_json()["lastError"] == "official Toolhub is unavailable"
    with db.session_scope() as s:
        anno = s.execute(select(ToolOverlay).where(ToolOverlay.kind == "annos")).scalar_one()
        assert anno.validation_errors == [{"field": "audiences", "message": "bad"}]
        crawler = s.execute(select(CrawlerUrl)).scalar_one()
        assert crawler.sync_status == "local_fallback"
        assert crawler.last_error == "official Toolhub is unavailable"


def test_write_list_and_favorite_success_store_official_sync_metadata(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/77/",
        api_cache.CacheableResponse(200, "application/json", b'{"id":77,"title":"old"}'),
    )
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/?page=1",
        api_cache.CacheableResponse(200, "application/json", b'{"results":[]}'),
    )
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url.removeprefix("https://toolhub.wikimedia.org"), kwargs.get("json")))
        if url.endswith("/api/user/favorites/"):
            return FakeResp({}, 204)
        return FakeResp({"id": 77}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    list_resp = client.post(
        "/v1/write/lists/",
        json={"clientId": "demo-list", "title": "List", "description": "d", "tools": ["my-tool"]},
        headers={"X-CSRF-Token": "tok"},
    )
    fav_resp = client.post(
        "/v1/write/user/favorites/",
        json={"name": "my-tool"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert list_resp.status_code == 201
    assert list_resp.get_json()["local"]["officialId"] == 77
    assert fav_resp.status_code == 200
    assert fav_resp.get_json()["toolhub"] == {"ok": True}
    assert calls[0][:2] == ("POST", "/api/lists/")
    assert calls[1][:2] == ("POST", "/api/user/favorites/")
    with db.session_scope() as s:
        stored_list = s.get(ToolList, "demo-list")
        assert stored_list.official_list_id == 77
        assert stored_list.sync_status == "official"
        assert stored_list.last_synced_at is not None
        favorite = s.execute(select(Favorite).where(Favorite.tool_name == "my-tool")).scalar_one()
        assert favorite.sync_status == "official"
        assert favorite.last_synced_at is not None
        assert s.query(ApiCache).count() == 0


def test_write_delete_failures_do_not_create_canonical_local_deletions(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "not owner"}, 403))
    resp = client.delete("/v1/write/tools/live-tool/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 403
    assert resp.get_json()["lastError"] == "not owner"
    assert client.delete("/v1/write/lists/12/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert client.delete("/v1/write/crawler/urls/9/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0
        assert s.query(ToolOverlay).count() == 0


def test_write_retry_and_discard_paths_for_fallback_records(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    tool_record = {
        "title": "Retry Tool",
        "description": "Retry me",
        "url": "https://retry.example",
        "repository": None,
        "license": None,
        "toolType": None,
        "keywords": [],
        "forWikis": [],
        "uiLanguages": [],
        "deprecated": False,
        "experimental": False,
        "origin": "api",
    }
    with db.session_scope() as s:
        s.add(
            ToolRecord(
                tool_name="retry-tool",
                user_id=uid,
                created_by_user_id=uid,
                record=tool_record,
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="edit-retry",
                user_id=uid,
                created_by_user_id=uid,
                patch={k: v for k, v in TOOL_WRITE_PAYLOAD.items() if k != "name"},
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolOverlay(
                kind="annos",
                tool_name="anno-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch={"audiences": ["editors"], "tasks": []},
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolList(
                client_id="demo-retry",
                user_id=uid,
                created_by_user_id=uid,
                title="Retry List",
                description="d",
                tools=["retry-tool"],
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolList(
                client_id="demo-discard",
                user_id=uid,
                created_by_user_id=uid,
                title="Discard List",
                description="d",
                tools=[],
                sync_status="local_fallback",
            )
        )
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://retry.example/toolinfo.json",
                sync_status="local_fallback",
            )
        )
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://discard.example/toolinfo.json",
                sync_status="local_fallback",
            )
        )
        s.flush()
        discard_crawler_id = (
            s.execute(select(CrawlerUrl.id).where(CrawlerUrl.url == "https://discard.example/toolinfo.json"))
            .scalars()
            .one()
        )
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="retry-tool", sync_status="local_fallback"))
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="discard-tool", sync_status="local_fallback"))

    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"id": 501}))
    assert (
        client.post(
            "/v1/write/tools/retry-tool/retry/",
            json={"kind": "new"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/write/tools/edit-retry/retry/",
            json={"kind": "edit"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            "/v1/write/tools/anno-tool/fallback/",
            json={"kind": "annotations"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert client.post("/v1/write/lists/demo-retry/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.delete("/v1/write/lists/demo-discard/fallback/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert (
        client.post(f"/v1/write/crawler/urls/{crawler_id}/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    )
    assert (
        client.delete(
            f"/v1/write/crawler/urls/{discard_crawler_id}/fallback/", headers={"X-CSRF-Token": "tok"}
        ).status_code
        == 200
    )
    assert client.post("/v1/write/user/favorites/retry-tool/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert (
        client.delete("/v1/write/user/favorites/discard-tool/fallback/", headers={"X-CSRF-Token": "tok"}).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/write/tools/missing/retry/",
            json={"kind": "nope"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0
        assert s.query(ToolOverlay).count() == 0
        assert s.get(ToolList, "demo-retry").sync_status == "official"
        assert s.get(ToolList, "demo-discard").deleted_at is not None
        assert s.get(CrawlerUrl, crawler_id).sync_status == "official"
        assert s.get(CrawlerUrl, discard_crawler_id) is None
        assert (
            s.execute(select(Favorite).where(Favorite.tool_name == "retry-tool")).scalar_one().sync_status == "official"
        )
        assert s.execute(select(Favorite).where(Favorite.tool_name == "discard-tool")).scalar_one_or_none() is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/write/tools/", "not-json"),
        ("POST", "/v1/write/tools/", {"name": "bad"}),
        ("POST", "/v1/write/tools/", {**TOOL_WRITE_PAYLOAD, "toolinfo_url": "http://example.org/toolinfo.json"}),
        ("DELETE", "/v1/write/tools/%20/", None),
        ("PUT", "/v1/write/tools/%20/annotations/", {}),
        ("PUT", "/v1/write/tools/my-tool/annotations/", "not-json"),
        ("POST", "/v1/write/lists/", "not-json"),
        ("POST", "/v1/write/lists/", {"title": ""}),
        ("PUT", "/v1/write/lists/not-a-number/", {"title": "L", "tools": []}),
        ("DELETE", "/v1/write/lists/not-a-number/", None),
        ("POST", "/v1/write/user/favorites/", "not-json"),
        ("POST", "/v1/write/user/favorites/", {}),
        ("DELETE", "/v1/write/user/favorites/%20/", None),
        ("POST", "/v1/write/crawler/urls/", "not-json"),
        ("POST", "/v1/write/crawler/urls/", {"url": "http://example.org/toolinfo.json"}),
        ("POST", "/v1/write/tools/%20/retry/", {"kind": "new"}),
        ("DELETE", "/v1/write/tools/%20/fallback/", {"kind": "new"}),
        ("DELETE", "/v1/write/tools/my-tool/fallback/", {}),
        ("POST", "/v1/write/user/favorites/%20/retry/", None),
        ("DELETE", "/v1/write/user/favorites/%20/fallback/", None),
    ],
)
def test_write_lifecycle_rejects_invalid_inputs(client, method, path, body):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    kwargs = {"headers": {"X-CSRF-Token": "tok"}}
    if isinstance(body, dict):
        kwargs["json"] = body
    elif isinstance(body, str):
        kwargs["data"] = body
    resp = client.open(method=method, path=path, **kwargs)
    assert resp.status_code == 400


def test_write_lifecycle_success_paths_for_deletes_annotations_and_crawler(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(
            ToolList(
                client_id="12",
                user_id=uid,
                created_by_user_id=uid,
                title="Official list cache",
                tools=["my-tool"],
                official_list_id=12,
            )
        )
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://example.org/toolinfo.json",
                official_crawler_url_id=9,
            )
        )
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="my-tool"))

    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"id": 99}, 200))
    assert (
        client.put(
            "/v1/write/tools/my-tool/annotations/",
            json={"audiences": [], "tasks": [], "icon": "https://example.org/icon.png"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert client.delete("/v1/write/tools/my-tool/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.delete("/v1/write/lists/12/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    crawler_add = client.post(
        "/v1/write/crawler/urls/",
        json={"url": "https://example.org/new-toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert crawler_add.status_code == 200
    assert crawler_add.get_json()["local"]["officialId"] == 99
    assert client.delete("/v1/write/crawler/urls/9/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.delete("/v1/write/user/favorites/my-tool/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    with db.session_scope() as s:
        assert s.get(ToolList, "12").deleted_at is not None
        crawler = s.execute(select(CrawlerUrl).where(CrawlerUrl.official_crawler_url_id == 9)).scalar_one()
        assert crawler.enabled is False
        assert s.execute(select(Favorite).where(Favorite.tool_name == "my-tool")).scalar_one_or_none() is None


def test_write_create_list_favorite_and_delete_fallback_paths(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "fallback please"}, 400))
    tool_resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    tool_retry_resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    list_resp = client.post(
        "/v1/write/lists/",
        json={"clientId": "demo-local", "title": "Local", "tools": ["my-tool"]},
        headers={"X-CSRF-Token": "tok"},
    )
    fav_resp = client.post(
        "/v1/write/user/favorites/",
        json={"name": "my-tool"},
        headers={"X-CSRF-Token": "tok"},
    )
    fav_delete_resp = client.delete("/v1/write/user/favorites/my-tool/", headers={"X-CSRF-Token": "tok"})
    assert tool_resp.status_code == 202
    assert tool_retry_resp.status_code == 202
    assert list_resp.status_code == 202
    assert fav_resp.status_code == 202
    assert fav_delete_resp.status_code == 202
    with db.session_scope() as s:
        assert (
            s.execute(select(ToolRecord).where(ToolRecord.tool_name == "my-tool")).scalar_one().sync_status
            == "local_fallback"
        )
        assert s.get(ToolList, "demo-local").sync_status == "local_fallback"
        assert s.execute(select(Favorite).where(Favorite.tool_name == "my-tool")).scalar_one_or_none() is None


def test_write_lifecycle_no_grant_branches_on_existing_retry_records(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="edit-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch=TOOL_WRITE_PAYLOAD,
            )
        )
        s.add(ToolList(client_id="demo-list", user_id=uid, created_by_user_id=uid, title="L", tools=[]))
        s.add(CrawlerUrl(user_id=uid, created_by_user_id=uid, url="https://example.org/toolinfo.json"))
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="my-tool"))
    cases = [
        ("DELETE", "/v1/write/tools/edit-tool/", None),
        ("PUT", "/v1/write/tools/edit-tool/annotations/", {}),
        ("PUT", "/v1/write/lists/12/", {"title": "L", "tools": []}),
        ("DELETE", "/v1/write/lists/12/", None),
        ("POST", "/v1/write/user/favorites/", {"name": "my-tool"}),
        ("DELETE", "/v1/write/user/favorites/my-tool/", None),
        ("POST", "/v1/write/crawler/urls/", {"url": "https://example.org/new.json"}),
        ("DELETE", "/v1/write/crawler/urls/9/", None),
        ("POST", "/v1/write/tools/edit-tool/retry/", {"kind": "edit"}),
        ("POST", "/v1/write/lists/demo-list/retry/", None),
        ("POST", f"/v1/write/crawler/urls/{crawler_id}/retry/", None),
        ("POST", "/v1/write/user/favorites/my-tool/retry/", None),
    ]
    for method, path, body in cases:
        kwargs = {"headers": {"X-CSRF-Token": "tok"}}
        if body is not None:
            kwargs["json"] = body
        assert client.open(method=method, path=path, **kwargs).status_code == 401


def test_write_retry_failure_and_missing_record_paths(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="edit-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch={k: v for k, v in TOOL_WRITE_PAYLOAD.items() if k != "name"},
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolRecord(
                tool_name="new-fail",
                user_id=uid,
                created_by_user_id=uid,
                record={
                    "title": "New Fail",
                    "description": "Retry fail",
                    "url": "https://new-fail.example",
                    "repository": None,
                    "license": None,
                    "toolType": None,
                    "keywords": [],
                    "forWikis": [],
                    "uiLanguages": [],
                    "deprecated": False,
                    "experimental": False,
                    "origin": "api",
                },
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolList(
                client_id="demo-fail",
                user_id=uid,
                created_by_user_id=uid,
                title="Fail List",
                tools=[],
                sync_status="local_fallback",
            )
        )
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://fail.example/toolinfo.json",
                sync_status="local_fallback",
            )
        )
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="fail-tool", sync_status="local_fallback"))
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "still bad"}, 400))
    assert (
        client.post(
            "/v1/write/tools/edit-tool/retry/",
            json={"kind": "edit"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/v1/write/tools/new-fail/retry/",
            json={"kind": "new"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 202
    )
    assert client.post("/v1/write/lists/demo-fail/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 202
    assert (
        client.post(f"/v1/write/crawler/urls/{crawler_id}/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 202
    )
    assert client.post("/v1/write/user/favorites/fail-tool/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 202
    missing_cases = [
        ("POST", "/v1/write/tools/missing/retry/", {"kind": "new"}),
        ("POST", "/v1/write/tools/missing/retry/", {"kind": "edit"}),
        ("DELETE", "/v1/write/tools/missing/fallback/", {"kind": "new"}),
        ("POST", "/v1/write/lists/missing/retry/", None),
        ("DELETE", "/v1/write/lists/missing/fallback/", None),
        ("POST", "/v1/write/crawler/urls/999/retry/", None),
        ("DELETE", "/v1/write/crawler/urls/999/fallback/", None),
        ("POST", "/v1/write/user/favorites/missing/retry/", None),
        ("DELETE", "/v1/write/user/favorites/missing/fallback/", None),
    ]
    for method, path, body in missing_cases:
        kwargs = {"headers": {"X-CSRF-Token": "tok"}}
        if body is not None:
            kwargs["json"] = body
        assert client.open(method=method, path=path, **kwargs).status_code == 404


def test_write_retry_permission_denials_for_owned_fallback_records(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(ToolList(client_id="demo-denied", user_id=uid, created_by_user_id=uid, title="L", tools=[]))
        s.add(CrawlerUrl(user_id=uid, created_by_user_id=uid, url="https://denied.example/toolinfo.json"))
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="denied-tool"))
    monkeypatch.setattr(
        authz,
        "can",
        lambda _user, action, _resource=None: action == authz.ACTION_TOOLHUB_WRITE,
    )
    assert client.post("/v1/write/lists/demo-denied/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert (
        client.post(f"/v1/write/crawler/urls/{crawler_id}/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    )
    assert (
        client.post("/v1/write/user/favorites/denied-tool/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    )


def test_write_lifecycle_local_permission_denials_after_official_rejection(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(
        authz,
        "can",
        lambda _user, action, _resource=None: action == authz.ACTION_TOOLHUB_WRITE,
    )
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "no local"}, 400))
    cases = [
        ("PUT", "/v1/write/tools/my-tool/annotations/", {"audiences": []}),
        ("POST", "/v1/write/lists/", {"title": "L", "tools": []}),
        ("POST", "/v1/write/user/favorites/", {"name": "my-tool"}),
        ("DELETE", "/v1/write/user/favorites/my-tool/", None),
        ("POST", "/v1/write/crawler/urls/", {"url": "https://example.org/toolinfo.json"}),
    ]
    for method, path, body in cases:
        kwargs = {"headers": {"X-CSRF-Token": "tok"}}
        if body is not None:
            kwargs["json"] = body
        assert client.open(method=method, path=path, **kwargs).status_code == 400


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


def test_oauth_login_refuses_to_derive_the_callback_from_request_headers(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.delenv("TOOLHUB_EVOLVED_BASE_URL", raising=False)
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    assert client.get("/oauth/login").status_code == 503  # no trusted callback → refuse to start the flow


def test_oauth_login_ignores_a_poisoned_host_header(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_EVOLVED_BASE_URL", "https://evolved.example")
    resp = client.get("/oauth/login", headers={"Host": "attacker.example", "X-Forwarded-Proto": "http"})
    location = resp.headers["Location"]
    assert "redirect_uri=https%3A%2F%2Fevolved.example%2Foauth%2Fcallback" in location
    assert "attacker.example" not in location


def test_oauth_callback_refuses_when_no_trusted_callback_is_configured(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    client.get("/oauth/login")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
        del sess["oauth_redirect_uri"]  # force the fallback path
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    resp = client.get(f"/oauth/callback?code=c&state={state}")
    assert resp.headers["Location"] == "/?login=error"


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


def test_oauth_callback_promotes_configured_evolved_role(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv(authz.ADMIN_USERS_ENV, "7")
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada", "is_authenticated": True}),
    )
    state = start_login(client)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/"
    data = client.get("/v1/user/").get_json()
    assert data["evolvedRole"] == "admin"
    assert authz.ACTION_OPERATOR in data["evolvedPermissions"]
    with db.session_scope() as s:
        assert s.query(User).one().role == "admin"


def test_oauth_logout(client):
    uid = add_user()
    toolhub.save_grant(uid, {"access_token": "at"})
    sign_in(client, uid)
    resp = client.post("/oauth/logout", data={"csrf": "tok"})
    assert resp.headers["Location"] == "/"
    assert client.get("/v1/user/").get_json() == {"authenticated": False}
    with db.session_scope() as s:
        assert s.query(ToolhubToken).count() == 0


def test_oauth_logout_without_session(client):
    resp = client.post("/oauth/logout")
    assert resp.headers["Location"] == "/?logout=error"  # no session → no valid CSRF token


def test_oauth_logout_tolerates_sessions_with_no_live_user(client):
    # csrf_ok never touches the database, so both of these reach the bump path
    # with nothing to bump: a session carrying a token but no uid, and one whose
    # account was deleted after the cookie was issued.
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    assert client.post("/oauth/logout", data={"csrf": "tok"}).headers["Location"] == "/"
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.delete(s.get(User, uid))
    assert client.post("/oauth/logout", data={"csrf": "tok"}).headers["Location"] == "/"


def test_oauth_logout_rejects_get_and_bad_csrf(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.get("/oauth/logout").status_code == 405  # not reachable from <img>/<a>
    resp = client.post("/oauth/logout", data={"csrf": "wrong"})
    assert resp.headers["Location"] == "/?logout=error"
    assert client.get("/v1/user/").get_json()["authenticated"] is True  # still signed in
