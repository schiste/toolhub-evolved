# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_catalog.py: the /v1/catalog/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it.
"""

import json
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import cache_prewarm  # noqa: E402
from backend import authz, catalog_projection, catalog_read, db, security, sync, tool_assets  # noqa: E402
from backend.models import CanonicalToolCache, CatalogCuration, CatalogFacetValue, User, utcnow  # noqa: E402


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


def test_catalog_health_is_a_local_cacheable_response(client, monkeypatch):
    monkeypatch.setattr(catalog_read, "replica_status", lambda: {"status": "idle"})

    response = client.get("/v1/catalog/health/")

    assert response.status_code == 200
    assert response.get_json() == {"status": "idle"}
    assert response.headers["Cache-Control"] == "public, max-age=30, stale-if-error=86400"


@pytest.mark.parametrize(
    ("path", "helper", "expected"),
    [
        ("/v1/catalog/search/tools/?q=alpha", "search_payload", {"kind": "search"}),
        ("/v1/catalog/ui/home/", "home_payload", {"kind": "home"}),
        ("/v1/catalog/lists/?featured=true", "collection_payload", {"kind": "lists"}),
        ("/v1/catalog/recent/", "collection_payload", {"kind": "recent"}),
    ],
)
def test_catalog_compatibility_dispatches_to_local_helpers(client, monkeypatch, path, helper, expected):
    if helper == "collection_payload":
        monkeypatch.setattr(catalog_read, helper, lambda route, _args: {"kind": route.removeprefix("/api/").strip("/")})
    else:
        monkeypatch.setattr(catalog_read, helper, lambda *_args: expected)

    response = client.get(path)

    assert response.status_code == 200
    assert response.get_json() == expected
    assert response.headers["X-Toolhub-Evolved-Source"] == "local-replica"


@pytest.mark.parametrize(("path", "helper"), [("tools/alpha", "tool_payload"), ("lists/42", "list_payload")])
def test_catalog_named_resources_are_local_and_report_missing_rows(client, monkeypatch, path, helper):
    monkeypatch.setattr(catalog_read, helper, lambda _name: {"name": "found"})
    assert client.get(f"/v1/catalog/{path}/").get_json() == {"name": "found"}

    monkeypatch.setattr(catalog_read, helper, lambda _name: None)
    missing = client.get(f"/v1/catalog/{path}/")
    assert missing.status_code == 404


def test_catalog_cached_compatibility_surface_never_falls_through_to_network(client, monkeypatch):
    monkeypatch.setattr(catalog_read, "replica_status", lambda: {"status": "idle"})
    monkeypatch.setattr(catalog_read, "cached_payload", lambda _url: None)
    missing = client.get("/v1/catalog/schema/?format=openapi")
    assert missing.status_code == 503
    assert missing.get_json()["replica"] == {"status": "idle"}

    monkeypatch.setattr(
        catalog_read,
        "cached_payload",
        lambda _url: (b'{"openapi":"3"}', "application/json", 200),
    )
    cached = client.get("/v1/catalog/schema/?format=openapi")
    assert cached.status_code == 200
    assert cached.get_json() == {"openapi": "3"}
    assert cached.headers["X-Toolhub-Evolved-Source"] == "local-replica"


def test_catalog_audit_feed_from_the_replica_withholds_private_activity(client, monkeypatch):
    """The replica mirrors upstream verbatim, private rows and all.

    app.py filters its own proxied copies of these bytes, so serving the same
    store through /v1/catalog must not become the way around that filter: which
    url a reader arrives on should not decide what they are shown.
    """
    feed = json.dumps(
        {
            "count": 2,
            "results": [
                {"id": 1, "content_type": "tool", "action": "updated"},
                {"id": 2, "content_type": "favorite", "action": "favorited"},
            ],
        }
    ).encode()
    monkeypatch.setattr(catalog_read, "cached_payload", lambda _url: (feed, "application/json", 200))

    response = client.get("/v1/catalog/auditlogs/?page_size=25")

    assert response.status_code == 200
    assert [row["id"] for row in response.get_json()["results"]] == [1]


def test_the_prewarmed_audit_url_is_the_one_the_catalog_route_looks_up(client):
    """Nothing stubbed on either side, because the bug was in between them.

    The prewarmer writes under the full upstream url and the route reads back
    under a url it rebuilds from the request. Both tests above hold a stub where
    the other half should be, so neither would notice the two spellings drifting
    apart -- which is the failure that produced an empty audit page.
    """
    feed = json.dumps(
        {
            "count": 109_061,
            "results": [
                {"id": 1, "content_type": "tool", "action": "updated"},
                {"id": 2, "content_type": "favorite", "action": "favorited"},
            ],
        }
    ).encode()

    class _Upstream:
        status_code = 200
        headers = {"content-type": "application/json"}

        def iter_content(self, _size):
            yield feed

        def close(self):
            pass

    class _Session:
        def get(self, _url, **_kwargs):
            return _Upstream()

    audit = [e for e in cache_prewarm.hot_endpoints() if e.path == "/api/auditlogs/"]
    assert audit, "nothing keeps the audit feed warm, so the route can only 503"
    assert cache_prewarm.run_once(_Session(), endpoints=audit).warmed == 1

    response = client.get("/v1/catalog/auditlogs/?page_size=25")

    assert response.status_code == 200
    assert response.headers["X-Toolhub-Evolved-Source"] == "local-replica"
    assert [row["id"] for row in response.get_json()["results"]] == [1]


def test_a_prewarmed_tool_history_is_readable_back_under_an_awkward_name(client):
    """The seam again, on the surface where the two spellings can differ.

    The prewarmer writes the name as it read it; the route gets its path from
    Flask already decoded and rebuilds the same string. Percent-encode on either
    side alone and the tool's history is unreachable forever -- rendered, since
    the view cannot tell a miss from an honest empty page, as a tool nobody has
    ever edited.
    """
    feed = json.dumps({"results": [{"id": 7, "comment": "edited"}]}).encode()

    class _Upstream:
        status_code = 200
        headers = {"content-type": "application/json"}

        def iter_content(self, _size):
            yield feed

        def close(self):
            pass

    class _Session:
        def get(self, _url, **_kwargs):
            return _Upstream()

    endpoints = cache_prewarm.tool_revision_endpoints(["a tool"])
    assert cache_prewarm.run_once(_Session(), endpoints=endpoints).warmed == 1

    response = client.get("/v1/catalog/tools/a%20tool/revisions/?page_size=20")

    assert response.status_code == 200
    assert [row["id"] for row in response.get_json()["results"]] == [7]


def test_catalog_non_activity_surfaces_are_served_byte_for_byte(client, monkeypatch):
    """Only the activity feeds are filtered.

    The filter reads a row's own fields, so a surface that merely happens to
    spell one of them the same way must still be passed through untouched --
    which is a property of the url, not of the payload.
    """
    runs = json.dumps({"results": [{"id": 7, "content_type": "favorite"}]}).encode()
    monkeypatch.setattr(catalog_read, "cached_payload", lambda _url: (runs, "application/json", 200))

    response = client.get("/v1/catalog/crawler/runs/?page_size=12")

    assert response.status_code == 200
    assert response.data == runs


def test_catalog_facets_are_available_as_an_independent_local_read(client):
    add_canonical("alpha", {"name": "alpha", "title": "Alpha", "tool_type": "web-app"})
    with db.session_scope() as session:
        session.add(CatalogFacetValue(tool_name="alpha", field="tool_type", value="web-app", label="web-app"))

    response = client.get("/v1/catalog/search/facets/")

    assert response.status_code == 200
    assert response.headers["X-Toolhub-Evolved-Source"] == "local-replica"
    assert response.get_json()["facets"]["_filter_tool_type"]["tool_type"]["buckets"] == [
        {"key": "web-app", "doc_count": 1}
    ]


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
