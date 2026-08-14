# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_catalog.py: the /v1/catalog/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import authz, catalog_projection, db, security, sync, tool_assets  # noqa: E402
from backend.models import CanonicalToolCache, CatalogCuration, User, utcnow  # noqa: E402


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


def add_canonical(name, record=None):
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name=name,
                record=record or {"name": name, "title": name.title(), "url": "https://official.example"},
                source_url="https://toolhub.wikimedia.org/api/tools/",
                fetched_at=now,
                expires_at=now,
                stale_until=now,
            )
        )


def create_curation(tool_name, *, created_by_user_id, review_status=sync.REVIEW_APPROVED, deleted_at=None):
    with db.session_scope() as s:
        row = CatalogCuration(
            tool_name=tool_name,
            created_by_user_id=created_by_user_id,
            patch={"url": "https://corrected.example"},
            rationale="Because the official URL is stale.",
            review_status=review_status,
            deleted_at=deleted_at,
        )
        s.add(row)
        s.flush()
        return row.id


def post_curation(client, name, **kwargs):
    payload = {
        "patch": {"url": "https://corrected.example"},
        "rationale": "Because the official URL is stale.",
    }
    payload.update(kwargs)
    return client.post(
        f"/v1/catalog/tools/{name}/curations/",
        json=payload,
        headers={"X-CSRF-Token": "tok"},
    )


# ---------------------------------------------------------------------------
# v1_catalog_tool_projection


def test_projection_not_found(client):
    resp = client.get("/v1/catalog/tools/nowhere/projection/")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "catalog projection not found"


def test_projection_found(client):
    add_canonical("alpha")
    catalog_projection.refresh_tool_names(["alpha"])
    resp = client.get("/v1/catalog/tools/alpha/projection/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["record"]["url"] == "https://official.example"
    assert resp.headers["ETag"]


# ---------------------------------------------------------------------------
# v1_catalog_tool_icon


def test_icon_not_found(client, monkeypatch):
    monkeypatch.setattr(tool_assets, "cached_asset", lambda name: None)
    resp = client.get("/v1/catalog/tools/alpha/icon/")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "cached icon not found"


def test_icon_ready(client, monkeypatch):
    body = b"\x89PNG-fake-bytes"
    monkeypatch.setattr(tool_assets, "cached_asset", lambda name: (body, "image/png", "digest123"))
    resp = client.get("/v1/catalog/tools/alpha/icon/")
    assert resp.status_code == 200
    assert resp.data == body
    assert resp.headers["Content-Type"] == "image/png"
    assert resp.headers["ETag"] == '"digest123"'
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in resp.headers["Content-Security-Policy"]
    assert "public" in resp.headers["Cache-Control"]


def test_icon_not_modified(client, monkeypatch):
    body = b"\x89PNG-fake-bytes"
    monkeypatch.setattr(tool_assets, "cached_asset", lambda name: (body, "image/png", "digest123"))
    resp = client.get("/v1/catalog/tools/alpha/icon/", headers={"If-None-Match": '"digest123"'})
    assert resp.status_code == 304
    assert resp.data == b""


# ---------------------------------------------------------------------------
# v1_catalog_curation


def test_curation_not_found(client):
    resp = client.get("/v1/catalog/curations/999/")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "catalog curation not found"


def test_curation_pending_is_hidden(client):
    uid = add_user()
    curation_id = create_curation("alpha", created_by_user_id=uid, review_status=sync.REVIEW_PENDING)
    resp = client.get(f"/v1/catalog/curations/{curation_id}/")
    assert resp.status_code == 404


def test_curation_deleted_is_hidden(client):
    uid = add_user()
    curation_id = create_curation(
        "alpha", created_by_user_id=uid, review_status=sync.REVIEW_APPROVED, deleted_at=utcnow()
    )
    resp = client.get(f"/v1/catalog/curations/{curation_id}/")
    assert resp.status_code == 404


def test_curation_approved_is_visible(client):
    uid = add_user()
    curation_id = create_curation("alpha", created_by_user_id=uid, review_status=sync.REVIEW_APPROVED)
    resp = client.get(f"/v1/catalog/curations/{curation_id}/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["toolName"] == "alpha"
    assert body["rationale"] == "Because the official URL is stale."
    assert "createdByUserId" not in body


# ---------------------------------------------------------------------------
# v1_catalog_curation_create


def test_curation_create_requires_tool_name(client):
    uid = add_user()
    sign_in(client, uid)
    resp = post_curation(client, "%20%20")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "tool name is required"


def test_curation_create_requires_json_object_body(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/catalog/tools/alpha/curations/",
        data="not json",
        headers={"X-CSRF-Token": "tok", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "curation body must be a JSON object"


def test_curation_create_validation_errors(client):
    uid = add_user()
    sign_in(client, uid)
    resp = post_curation(client, "alpha", patch={"not_a_curatable_field": "nope"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "curation validation failed"
    assert body["validationErrors"]


def test_curation_create_requires_rationale(client):
    uid = add_user()
    sign_in(client, uid)
    resp = post_curation(client, "alpha", rationale="   ")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "rationale is required"
    assert body["validationErrors"][0]["field"] == "rationale"


def test_curation_create_canonical_tool_missing(client):
    uid = add_user()
    sign_in(client, uid)
    resp = post_curation(client, "does-not-exist-in-canonical-cache")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "canonical tool not found"


def test_curation_create_success(client):
    uid = add_user()
    sign_in(client, uid)
    add_canonical("alpha")
    resp = post_curation(client, "alpha")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["ok"] is True
    assert body["source"] == sync.SOURCE_LOCAL
    assert body["syncStatus"] == sync.SYNC_EVOLVED_REAL
    item = body["item"]
    assert item["kind"] == "catalog-curations"
    assert item["data"]["toolName"] == "alpha"
    assert item["data"]["reviewStatus"] == sync.REVIEW_PENDING
    with db.session_scope() as s:
        row = s.get(CatalogCuration, item["id"])
        assert row is not None
        assert row.created_by_user_id == uid
