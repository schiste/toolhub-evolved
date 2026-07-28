# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for crawler toolinfo.json discovery."""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
from backend import authz, db, security, toolhub  # noqa: E402
from backend.author_claims import ToolforgeMembershipProvider  # noqa: E402
from backend.models import User  # noqa: E402


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


def test_toolinfo_discovery_uses_origin_root(client, monkeypatch):
    uid = add_user("Schiste")
    sign_in(client, uid)
    calls = []

    def fake_toolinfo(url):
        calls.append(url)
        return {"name": "root-tool", "title": "Root Tool"}

    monkeypatch.setattr(v1_api, "_fetch_toolinfo_json_once", fake_toolinfo)
    monkeypatch.setattr(v1_api, "_fetch_sitemap_xml_once", lambda _url: pytest.fail("sitemap should not be fetched"))

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

    def fake_toolinfo(url):
        calls.append(url)
        if url == "https://tool.example/toolinfo.json":
            raise http_error(404)
        return [{"name": "sitemap-tool"}, {"name": "sitemap-tool"}]

    monkeypatch.setattr(v1_api, "_fetch_toolinfo_json_once", fake_toolinfo)
    monkeypatch.setattr(
        v1_api,
        "_fetch_sitemap_xml_once",
        lambda url: (
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

    monkeypatch.setattr(v1_api, "_fetch_toolinfo_json_once", lambda _url: (_ for _ in ()).throw(http_error(404)))
    monkeypatch.setattr(v1_api, "_fetch_sitemap_xml_once", lambda _url: (_ for _ in ()).throw(http_error(404)))

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
    resp = client.post(
        "/v1/crawler/toolinfo-discovery/",
        json={"url": "https://"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["validationErrors"] == [{"field": "url", "message": "tool URL must include a host."}]
