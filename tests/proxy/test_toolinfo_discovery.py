# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for crawler toolinfo.json discovery."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
from backend import authz, db, security, toolhub, toolinfo_discovery  # noqa: E402
from backend.author_claims import ToolforgeMembershipProvider  # noqa: E402
from backend.models import ToolAuthorClaim, ToolinfoDiscovery, ToolinfoDiscoveryMeta, User, utcnow  # noqa: E402


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
        sess["epoch"] = epoch


def http_error(status):
    exc = toolhub.requests.HTTPError(str(status))
    exc.response = type("Resp", (), {"status_code": status})()
    return exc


class FakeResp:
    def __init__(self, body=b"{}", status=200):
        self._body = body
        self.status_code = status
        self.is_redirect = 300 <= status < 400
        self.is_permanent_redirect = status in (301, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise http_error(self.status_code)

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_toolinfo_discovery_uses_origin_root(client, monkeypatch):
    uid = add_user("Schiste")
    sign_in(client, uid)
    calls = []

    def fake_toolinfo(url, _session=None):
        calls.append(url)
        return {"name": "root-tool", "title": "Root Tool"}

    monkeypatch.setattr(toolinfo_discovery, "fetch_toolinfo_json_once", fake_toolinfo)
    monkeypatch.setattr(
        toolinfo_discovery, "fetch_sitemap_xml_once", lambda _url, _session=None: pytest.fail("sitemap should not be fetched")
    )

    resp = client.post(
        "/v1/crawler/toolinfo-discovery/",
        json={"url": "https://tool.example/app"},
        headers={"X-CSRF-Token": "tok"},
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["method"] == "root"
    assert data["toolinfoUrl"] == "https://tool.example/toolinfo.json"
    assert data["toolNames"] == ["root-tool"]
    assert calls == ["https://tool.example/toolinfo.json"]


def test_toolinfo_discovery_uses_sitemap_after_root_404(client, monkeypatch):
    uid = add_user("Schiste")
    sign_in(client, uid)
    calls = []

    def fake_toolinfo(url, _session=None):
        calls.append(url)
        if url == "https://tool.example/toolinfo.json":
            raise http_error(404)
        return [{"name": "sitemap-tool"}, {"name": "sitemap-tool"}]

    monkeypatch.setattr(toolinfo_discovery, "fetch_toolinfo_json_once", fake_toolinfo)
    monkeypatch.setattr(
        toolinfo_discovery,
        "fetch_sitemap_xml_once",
        lambda url, _session=None: (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://other.example/toolinfo.json</loc></url>"
            "<url><loc>https://tool.example/docs/</loc></url>"
            "<url><loc>https://tool.example/meta/toolinfo.json</loc></url>"
            "</urlset>"
            if url == "https://tool.example/sitemap.xml"
            else pytest.fail(f"unexpected sitemap {url}")
        ),
    )

    resp = client.post(
        "/v1/crawler/toolinfo-discovery/",
        json={"url": "https://tool.example/"},
        headers={"X-CSRF-Token": "tok"},
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["method"] == "sitemap"
    assert data["toolinfoUrl"] == "https://tool.example/meta/toolinfo.json"
    assert data["toolNames"] == ["sitemap-tool"]
    assert calls == ["https://tool.example/toolinfo.json", "https://tool.example/meta/toolinfo.json"]


def test_toolinfo_discovery_reports_not_found_when_root_and_sitemap_404(client, monkeypatch):
    uid = add_user("Schiste")
    sign_in(client, uid)

    monkeypatch.setattr(
        toolinfo_discovery, "fetch_toolinfo_json_once", lambda _url, _session=None: (_ for _ in ()).throw(http_error(404))
    )
    monkeypatch.setattr(
        toolinfo_discovery, "fetch_sitemap_xml_once", lambda _url, _session=None: (_ for _ in ()).throw(http_error(404))
    )

    resp = client.post(
        "/v1/crawler/toolinfo-discovery/",
        json={"url": "https://missing.example/tool"},
        headers={"X-CSRF-Token": "tok"},
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is False
    assert data["status"] == "not_found"
    assert data["lastError"] == "toolinfo.json not found at root and sitemap.xml could not be used"
    assert [attempt["url"] for attempt in data["attempts"]] == [
        "https://missing.example/toolinfo.json",
        "https://missing.example/sitemap.xml",
    ]


def test_toolinfo_discovery_validates_url_and_session(client):
    assert client.post("/v1/crawler/toolinfo-discovery/", json={"url": "https://tool.example"}).status_code == 401
    uid = add_user("Schiste")
    sign_in(client, uid)
    assert (
        client.post(
            "/v1/crawler/toolinfo-discovery/",
            json={},
            headers={"X-CSRF-Token": "tok"},
        )
        .get_json()["validationErrors"]
        == [{"field": "url", "message": "tool URL is required."}]
    )
    resp = client.post(
        "/v1/crawler/toolinfo-discovery/",
        json={"url": "https://"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["validationErrors"] == [{"field": "url", "message": "tool URL must include a host."}]
    assert (
        client.post(
            "/v1/crawler/toolinfo-discovery/",
            json={"url": "https://[broken"},
            headers={"X-CSRF-Token": "tok"},
        )
        .get_json()["validationErrors"]
        == [{"field": "url", "message": "tool URL is not a valid URL."}]
    )
    assert (
        client.post(
            "/v1/crawler/toolinfo-discovery/",
            json={"url": f"https://example.org/{'x' * 2100}"},
            headers={"X-CSRF-Token": "tok"},
        )
        .get_json()["validationErrors"]
        == [{"field": "url", "message": "tool URL must be 2000 characters or fewer."}]
    )
    assert (
        client.post(
            "/v1/crawler/toolinfo-discovery/",
            json={"url": "https://example.org/with space"},
            headers={"X-CSRF-Token": "tok"},
        )
        .get_json()["validationErrors"]
        == [{"field": "url", "message": "tool URL cannot contain spaces."}]
    )
    assert (
        client.post(
            "/v1/crawler/toolinfo-discovery/",
            data="[]",
            headers={"X-CSRF-Token": "tok", "Content-Type": "application/json"},
        ).status_code
        == 400
    )


def test_discovery_guard_and_fetch_helpers(monkeypatch):
    with pytest.raises(ValueError, match="only public https"):
        toolinfo_discovery._require_public_https("http://example.org/toolinfo.json")

    monkeypatch.setattr(toolinfo_discovery.socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(OSError("nx")))
    with pytest.raises(ValueError, match="cannot resolve"):
        toolinfo_discovery._require_public_https("https://missing.example/toolinfo.json")

    monkeypatch.setattr(
        toolinfo_discovery.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="non-public"):
        toolinfo_discovery._require_public_https("https://private.example/toolinfo.json")

    monkeypatch.setattr(
        toolinfo_discovery.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))],
    )
    toolinfo_discovery._require_public_https("https://public.example/toolinfo.json")

    monkeypatch.setattr(toolinfo_discovery, "_require_public_https", lambda _url: None)
    session = FakeSession(FakeResp(b'{"name":"ok"}'))
    assert toolinfo_discovery.fetch_toolinfo_json_once("https://public.example/toolinfo.json", session) == {"name": "ok"}
    assert session.calls[0][1]["allow_redirects"] is False
    assert toolinfo_discovery.fetch_sitemap_xml_once("https://public.example/sitemap.xml", FakeSession(FakeResp(b"<x/>"))) == "<x/>"

    with pytest.raises(ValueError, match="redirects"):
        toolinfo_discovery.fetch_toolinfo_json_once("https://public.example/toolinfo.json", FakeSession(FakeResp(status=302)))
    monkeypatch.setattr(toolinfo_discovery, "MAX_BODY_BYTES", 1)
    with pytest.raises(ValueError, match="larger than"):
        toolinfo_discovery.fetch_toolinfo_json_once(
            "https://public.example/toolinfo.json",
            FakeSession(FakeResp(b"{}")),
        )


def test_discovery_helpers_cover_filtering_and_payload_branches():
    assert toolinfo_discovery._toolinfo_names("bad") == []
    assert toolinfo_discovery._sitemap_toolinfo_urls("<not xml", sitemap_url="https://tool.example/sitemap.xml", origin="https://tool.example") == []
    long_url = f"https://tool.example/{'x' * 2100}/toolinfo.json"
    xml = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>http://tool.example/toolinfo.json</loc></url>"
        "<url><loc>https://other.example/toolinfo.json</loc></url>"
        "<url><loc>https://tool.example/docs/</loc></url>"
        f"<url><loc>{long_url}</loc></url>"
        "<url><loc>https://tool.example/ok/toolinfo.json</loc></url>"
        "<url><loc>https://tool.example/ok/toolinfo.json</loc></url>"
        "</urlset>"
    )
    assert toolinfo_discovery._sitemap_toolinfo_urls(
        xml,
        sitemap_url="https://tool.example/sitemap.xml",
        origin="https://tool.example",
    ) == ["https://tool.example/ok/toolinfo.json"]
    assert toolinfo_discovery.tool_discovery_candidate_url({"toolinfo_url": " https://t.example/toolinfo.json "}) == "https://t.example/toolinfo.json"
    assert toolinfo_discovery.tool_discovery_candidate_url({"toolinfoUrl": "https://camel.example/toolinfo.json"}) == "https://camel.example/toolinfo.json"
    assert toolinfo_discovery.tool_discovery_candidate_url({"url": 7}) == ""
    assert toolinfo_discovery.discovery_payload(None)["status"] == "pending"
    row = ToolinfoDiscovery(
        tool_name="bad-lists",
        tool_url="https://bad.example",
        status="",
        tool_names={},
        attempts={},
        source="",
        sync_status="",
    )
    payload = toolinfo_discovery.discovery_payload(row)
    assert payload["status"] == "pending"
    assert payload["toolNames"] == []
    assert payload["attempts"] == []
    assert payload["source"] == "local"
    assert payload["syncStatus"] == "evolved_real"


def test_sitemap_discovery_stops_at_configured_limit(monkeypatch):
    monkeypatch.setattr(toolinfo_discovery, "MAX_SITEMAP_LOCS", 1)
    xml = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://tool.example/one/toolinfo.json</loc></url>"
        "<url><loc>https://tool.example/two/toolinfo.json</loc></url>"
        "</urlset>"
    )

    assert toolinfo_discovery._sitemap_toolinfo_urls(
        xml,
        sitemap_url="https://tool.example/sitemap.xml",
        origin="https://tool.example",
    ) == ["https://tool.example/one/toolinfo.json"]


def test_discovery_reports_root_errors_and_empty_sitemaps(monkeypatch):
    monkeypatch.setattr(
        toolinfo_discovery,
        "fetch_toolinfo_json_once",
        lambda _url, _session=None: (_ for _ in ()).throw(ValueError("DNS failed")),
    )
    data = toolinfo_discovery.discover_toolinfo_url("https://broken.example/tool")
    assert data["status"] == "error"
    assert data["lastError"] == "DNS failed"

    monkeypatch.setattr(
        toolinfo_discovery,
        "fetch_toolinfo_json_once",
        lambda _url, _session=None: (_ for _ in ()).throw(http_error(404)),
    )
    monkeypatch.setattr(toolinfo_discovery, "fetch_sitemap_xml_once", lambda _url, _session=None: "<urlset />")
    data = toolinfo_discovery.discover_toolinfo_url("https://empty.example/tool")
    assert data["status"] == "not_found"
    assert data["lastError"] == "toolinfo.json not found at root or in sitemap.xml"


def test_discovery_reports_not_found_when_sitemap_candidates_404(monkeypatch):
    calls = []

    def fake_toolinfo(url, _session=None):
        calls.append(url)
        raise http_error(404)

    monkeypatch.setattr(toolinfo_discovery, "fetch_toolinfo_json_once", fake_toolinfo)
    monkeypatch.setattr(
        toolinfo_discovery,
        "fetch_sitemap_xml_once",
        lambda _url, _session=None: (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://empty.example/meta/toolinfo.json</loc></url>"
            "</urlset>"
        ),
    )

    data = toolinfo_discovery.discover_toolinfo_url("https://empty.example/tool")

    assert data["status"] == "not_found"
    assert calls == ["https://empty.example/toolinfo.json", "https://empty.example/meta/toolinfo.json"]


def test_ensure_pending_records_no_url_candidates():
    db.configure("sqlite://")
    db.init_schema()

    payloads = toolinfo_discovery.ensure_pending_for_candidates({"nameless-url": {"tool": {"name": "nameless-url"}}})

    assert payloads["nameless-url"]["status"] == "no_url"
    assert payloads["nameless-url"]["lastError"] == "official Toolhub record has no URL to probe"
    with db.session_scope() as s:
        row = s.query(ToolinfoDiscovery).one()
        assert row.tool_name == "nameless-url"
        assert row.status == "no_url"


def test_upsert_helpers_update_existing_rows_and_error_expiry():
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        row = toolinfo_discovery.upsert_pending(s, tool_name="changing-tool", tool_url="https://old.example/tool")
        s.flush()
        assert row.tool_url == "https://old.example/tool"
        toolinfo_discovery.upsert_pending(s, tool_name="changing-tool", tool_url="https://new.example/tool")
        assert row.tool_url == "https://new.example/tool"
        assert row.expires_at is not None
        toolinfo_discovery.upsert_no_url(s, tool_name="changing-tool", last_error="no official URL")
        assert row.status == "no_url"
        assert row.toolinfo_url is None
        error_row = toolinfo_discovery.upsert_result(
            s,
            tool_name="error-tool",
            tool_url="https://error.example/tool",
            result={"status": "error", "lastError": "timeout"},
        )
        unknown_row = toolinfo_discovery.upsert_result(
            s,
            tool_name="unknown-tool",
            tool_url="https://unknown.example/tool",
            result={"status": "unknown"},
        )
        assert error_row.expires_at is not None
        assert unknown_row.expires_at is not None


def test_toolhub_listing_page_accepts_list_and_invalid_payloads(monkeypatch):
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_a, **_k: [{"name": "list-tool"}, "bad"])
    assert toolinfo_discovery._toolhub_tool_listing_page(1) == ([{"name": "list-tool"}], False)
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_a, **_k: "bad")
    assert toolinfo_discovery._toolhub_tool_listing_page(1) == ([], False)


def test_seed_listing_row_handles_detail_errors(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    monkeypatch.setattr(
        toolinfo_discovery,
        "_tool_url_from_listing_row",
        lambda _row: (_ for _ in ()).throw(toolhub.ToolhubAPIError(503, {})),
    )

    assert toolinfo_discovery._seed_listing_row({"name": "busy-tool"}) == {"seeded": 0, "skipped": 1, "errors": 1}


def test_seed_from_toolhub_listing_walks_pages_and_records_urls(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    calls = []

    def fake_public_api_get(path, *, params=None):
        calls.append((path, params))
        if path == "/api/tools/" and params["page"] == 1:
            return {
                "results": [
                    {"name": "root-tool", "url": "https://root.example/app"},
                    {"name": "direct-tool", "toolinfo_url": "https://direct.example/toolinfo.json"},
                    {"name": "detail-tool"},
                    {"title": "Nameless"},
                ],
                "next": "https://toolhub.example/api/tools/?page=2",
            }
        if path == "/api/tools/detail-tool/":
            return {"name": "detail-tool", "url": "https://detail.example/tool"}
        raise AssertionError((path, params))

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)

    summary = toolinfo_discovery.seed_from_toolhub_listing(limit=10)

    assert summary == {"seeded": 3, "skipped": 1, "errors": 0}
    assert calls == [
        ("/api/tools/", {"page": 1, "page_size": 10}),
        ("/api/tools/detail-tool/", None),
    ]
    with db.session_scope() as s:
        rows = {row.tool_name: row for row in s.query(ToolinfoDiscovery).all()}
        assert rows["root-tool"].tool_url == "https://root.example/app"
        assert rows["direct-tool"].tool_url == "https://direct.example/toolinfo.json"
        assert rows["detail-tool"].tool_url == "https://detail.example/tool"
        assert s.get(ToolinfoDiscoveryMeta, "toolhub_tools_page").value == "2"


def test_seed_from_toolhub_listing_handles_zero_limits_empty_pages_and_limit_break(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    assert toolinfo_discovery.seed_from_toolhub_listing(limit=0) == {"seeded": 0, "skipped": 0, "errors": 0}
    assert toolinfo_discovery.seed_from_toolhub_listing(limit=1, max_pages=0) == {
        "seeded": 0,
        "skipped": 0,
        "errors": 0,
    }

    monkeypatch.setattr(toolhub, "public_api_get", lambda *_a, **_k: {"results": []})
    assert toolinfo_discovery.seed_from_toolhub_listing(limit=1) == {"seeded": 0, "skipped": 0, "errors": 0}
    with db.session_scope() as s:
        assert s.get(ToolinfoDiscoveryMeta, "toolhub_tools_page").value == "1"

    def two_rows(path, *, params=None):
        assert path == "/api/tools/"
        assert params == {"page": 1, "page_size": 1}
        return {"results": [{"name": "first-tool", "url": "https://first.example/tool"}], "next": "next"}

    monkeypatch.setattr(toolhub, "public_api_get", two_rows)
    assert toolinfo_discovery.seed_from_toolhub_listing(limit=1) == {"seeded": 1, "skipped": 0, "errors": 0}
    with db.session_scope() as s:
        assert s.get(ToolinfoDiscoveryMeta, "toolhub_tools_page").value == "2"


def test_seed_from_toolhub_listing_records_no_url_cursor_wrap_and_errors(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        s.add(ToolinfoDiscoveryMeta(key="toolhub_tools_page", value="bad"))

    def no_url_page(path, *, params=None):
        if path == "/api/tools/no-url-tool/":
            return {"name": "no-url-tool"}
        assert path == "/api/tools/"
        assert params == {"page": 1, "page_size": 2}
        return {"results": [{"name": "no-url-tool"}], "next": None}

    monkeypatch.setattr(toolhub, "public_api_get", no_url_page)
    summary = toolinfo_discovery.seed_from_toolhub_listing(limit=2)

    assert summary == {"seeded": 0, "skipped": 1, "errors": 0}
    with db.session_scope() as s:
        row = s.query(ToolinfoDiscovery).filter_by(tool_name="no-url-tool").one()
        assert row.status == "no_url"
        assert s.get(ToolinfoDiscoveryMeta, "toolhub_tools_page").value == "1"

    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda *_a, **_k: (_ for _ in ()).throw(toolhub.ToolhubAPIError(503, {})),
    )
    assert toolinfo_discovery.seed_from_toolhub_listing(limit=2) == {"seeded": 0, "skipped": 0, "errors": 1}


def test_toolhub_detail_for_name_handles_failures_and_non_objects(monkeypatch):
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_a, **_k: ["not", "a", "dict"])
    assert toolinfo_discovery._toolhub_detail_for_name("list-payload") is None
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_a, **_k: (_ for _ in ()).throw(toolhub.ToolhubAPIError(503, {})))
    assert toolinfo_discovery._toolhub_detail_for_name("busy") is None


def test_refresh_known_discoveries_seeds_from_author_claims(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        user = User(wm_sub="7", username="Ada")
        s.add(user)
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada",
                toolhub_username="Ada",
                verification_status="unverified",
                verification_method="author_display_name",
            )
        )

    monkeypatch.setattr(toolinfo_discovery, "seed_from_toolhub_listing", lambda limit=100: {"seeded": 0, "skipped": 0, "errors": 0})
    monkeypatch.setattr(
        toolinfo_discovery,
        "_toolhub_detail_for_name",
        lambda name: {"name": name, "url": "https://ada.example/tool"},
    )
    monkeypatch.setattr(
        toolinfo_discovery,
        "discover_toolinfo_url",
        lambda url, _session=None: {
            "ok": True,
            "status": "found",
            "method": "root",
            "inputUrl": url,
            "toolinfoUrl": "https://ada.example/toolinfo.json",
            "toolNames": ["ada-tool"],
            "attempts": [{"url": "https://ada.example/toolinfo.json", "method": "root", "ok": True}],
        },
    )

    summary = toolinfo_discovery.refresh_known_discoveries()

    assert summary == {"refreshed": 1, "seeded": 1, "found": 1, "missing": 0, "errors": 0, "skipped": 0}
    with db.session_scope() as s:
        row = s.query(ToolinfoDiscovery).one()
        assert row.tool_name == "ada-tool"
        assert row.tool_url == "https://ada.example/tool"
        assert row.status == "found"
        assert row.toolinfo_url == "https://ada.example/toolinfo.json"


def test_refresh_known_discoveries_skips_queued_and_fresh_claims(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            ToolinfoDiscovery(
                tool_name="queued-tool",
                tool_url="https://queued.example/tool",
                status="pending",
                expires_at=now - timedelta(seconds=1),
            )
        )
        s.add(
            ToolinfoDiscovery(
                tool_name="fresh-tool",
                tool_url="https://fresh.example/tool",
                status="found",
                expires_at=now + timedelta(days=1),
            )
        )
        for tool_name in ("queued-tool", "fresh-tool"):
            s.add(
                ToolAuthorClaim(
                    tool_name=tool_name,
                    author_name="Ada",
                    toolhub_username="Ada",
                    verification_status="unverified",
                    verification_method="author_display_name",
                )
            )

    monkeypatch.setattr(toolinfo_discovery, "seed_from_toolhub_listing", lambda **_kwargs: {"seeded": 0, "skipped": 0, "errors": 0})
    monkeypatch.setattr(
        toolinfo_discovery,
        "discover_toolinfo_url",
        lambda _url, _session=None: {"ok": False, "status": "error", "attempts": [], "lastError": "timeout"},
    )

    assert toolinfo_discovery.refresh_known_discoveries(limit=2) == {
        "refreshed": 1,
        "seeded": 0,
        "found": 0,
        "missing": 0,
        "errors": 1,
        "skipped": 0,
    }


def test_refresh_known_discoveries_stops_claim_seeding_at_limit(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        s.add(
            ToolinfoDiscovery(
                tool_name="queued-tool",
                tool_url="https://queued.example/tool",
                status="pending",
                expires_at=utcnow() - timedelta(seconds=1),
            )
        )
        s.add(
            ToolAuthorClaim(
                tool_name="extra-tool",
                author_name="Ada",
                toolhub_username="Ada",
                verification_status="unverified",
                verification_method="author_display_name",
            )
        )

    monkeypatch.setattr(toolinfo_discovery, "seed_from_toolhub_listing", lambda **_kwargs: {"seeded": 0, "skipped": 0, "errors": 0})
    monkeypatch.setattr(
        toolinfo_discovery,
        "discover_toolinfo_url",
        lambda _url, _session=None: {"ok": False, "status": "not_found", "attempts": [], "lastError": "missing"},
    )

    assert toolinfo_discovery.refresh_known_discoveries(limit=1)["refreshed"] == 1


def test_refresh_known_discoveries_handles_stale_rows_and_missing_urls(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        s.add(
            ToolinfoDiscovery(
                tool_name="missing-tool",
                tool_url="https://missing.example/tool",
                status="pending",
                expires_at=utcnow() - timedelta(seconds=1),
            )
        )
        s.add(
            ToolAuthorClaim(
                tool_name="no-url-tool",
                author_name="Ada",
                toolhub_username="Ada",
                verification_status="unverified",
                verification_method="author_display_name",
            )
        )

    monkeypatch.setattr(toolinfo_discovery, "seed_from_toolhub_listing", lambda limit=100: {"seeded": 0, "skipped": 0, "errors": 0})
    monkeypatch.setattr(toolinfo_discovery, "_toolhub_detail_for_name", lambda _name: {"name": "no-url-tool"})
    monkeypatch.setattr(
        toolinfo_discovery,
        "discover_toolinfo_url",
        lambda url, _session=None: {
            "ok": False,
            "status": "not_found",
            "inputUrl": url,
            "lastError": "toolinfo.json not found at root or in sitemap.xml",
            "attempts": [],
        },
    )

    summary = toolinfo_discovery.refresh_known_discoveries()

    assert summary == {"refreshed": 1, "seeded": 0, "found": 0, "missing": 1, "errors": 0, "skipped": 1}
    with db.session_scope() as s:
        row = s.query(ToolinfoDiscovery).filter_by(tool_name="missing-tool").one()
        assert row.status == "not_found"
        assert row.last_error == "toolinfo.json not found at root or in sitemap.xml"
