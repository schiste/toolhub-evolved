# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_me.py: the /v1/me/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it.

A few branches only fire on a delete-mid-request race (the signed-in user's
row vanishing between the login check and a later read in the same request).
Those are exercised with a scoped monkeypatch on sqlalchemy.orm.Session.get
that lets the first N real lookups for that user id through, then returns
None — simulating the row disappearing partway through the request without
touching the login flow's own lookups.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.orm import Session as OrmSession

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import authz, db, people_index, security  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    PersonAccountBinding,
    PersonProfile,
    ToolAuthorClaim,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolPersonRelationship,
    User,
    utcnow,
)


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


def vanish_user_after(monkeypatch, uid, after_calls):
    """Let the first `after_calls` Session.get(User, uid) lookups through, then return None.

    Simulates the user's row being deleted partway through a single request:
    the login guard's own lookup (cached per-request via flask.g) always
    succeeds, and any lookup counted within the budget also succeeds, so
    the request reaches the view's own later re-fetch before it starts
    seeing a vanished row.
    """
    orig_get = OrmSession.get
    calls = {"n": 0}

    def fake_get(self, entity, ident=None, *args, **kwargs):
        if entity is User and ident == uid:
            calls["n"] += 1
            if calls["n"] > after_calls:
                return None
        return orig_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "get", fake_get)


def link_person(uid, *, tool_name="alpha-tool", uncached_tool_name=None):
    """Give a user a linked Person with a verified relationship, a matching
    author claim, and a verified Toolforge account binding + membership.

    Exercises the branches of _canonical_account_tools that only run when
    there is at least one resolved relationship for the linked person: the
    claims-by-tool loop, the relationships-by-tool loop, and the Toolforge
    membership lookup. When `uncached_tool_name` is given, an extra
    relationship is added for a tool with no CanonicalToolCache row, so the
    `record is None -> continue` branch also runs.
    """
    with db.session_scope() as s:
        user = s.get(User, uid)
        person = people_index.link_user(s, user)
        s.flush()
        person_id = person.id
    with db.session_scope() as s:
        now = utcnow()
        s.add(
            CanonicalToolCache(
                tool_name=tool_name,
                record={"name": tool_name, "title": "Alpha Tool", "url": f"https://example.org/{tool_name}"},
                expires_at=now + timedelta(days=1),
                stale_until=now + timedelta(days=2),
            )
        )
        s.add(
            ToolPersonRelationship(
                tool_name=tool_name,
                person_id=person_id,
                relationship_type="maintainer",
                verification_status="verified",
                evidence_count=1,
            )
        )
        s.add(
            ToolAuthorClaim(
                tool_name=tool_name,
                author_name="Ada",
                toolhub_username="Ada",
                user_id=uid,
                requested_relationship="maintainer",
            )
        )
        s.add(PersonAccountBinding(provider="toolforge", external_id="1001", person_id=person_id, status="verified"))
        s.add(ToolforgeAccountProjection(uid_number="1001", uid="ada"))
        s.add(ToolforgeMembershipProjection(uid_number="1001", tool_name=tool_name))
        if uncached_tool_name:
            s.add(
                ToolPersonRelationship(
                    tool_name=uncached_tool_name,
                    person_id=person_id,
                    relationship_type="author",
                    verification_status="unverified",
                )
            )
    return person_id


# ---------------------------------------------------------------------------
# v1_me_tools / _canonical_account_tools


def test_me_tools_no_relationships_returns_empty_summaries(client):
    """No linked person data: verified/possible stay empty and summaries short-circuit."""
    uid = add_user()
    sign_in(client, uid)
    resp = client.get("/v1/me/tools/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["person"] == {"id": body["personId"], "displayName": "Ada"}
    assert body["verified"] == []
    assert body["possible"] == []
    assert body["summaries"] == {}


def test_me_tools_stored_user_vanishes_mid_request(client, monkeypatch):
    """The re-fetch inside _canonical_account_tools finds the row gone."""
    uid = add_user()
    sign_in(client, uid)
    vanish_user_after(monkeypatch, uid, after_calls=2)
    resp = client.get("/v1/me/tools/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["verified"] == []
    assert body["possible"] == []
    assert body["errors"] == []


def test_me_tools_with_verified_relationship_and_claim(client):
    """A verified relationship with a matching claim populates claims/relationships,
    resolves the caller's Toolforge tool membership, and skips a relationship
    whose tool has no canonical cache row."""
    uid = add_user()
    sign_in(client, uid)
    link_person(uid, tool_name="alpha-tool", uncached_tool_name="uncached-tool")
    resp = client.get("/v1/me/tools/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["counts"]["verified"] == 1
    assert body["toolforgeToolNames"] == ["alpha-tool"]
    assert {item["tool"]["name"] for item in body["verified"] + body["possible"]} == {"alpha-tool"}
    item = body["verified"][0]
    assert item["tool"]["name"] == "alpha-tool"
    # claims_by_tool contributes the stored claim; edge_claims contributes the
    # resolved relationship's own claim shape.
    assert len(item["claims"]) == 2
    assert len(item["relationships"]) == 1


# ---------------------------------------------------------------------------
# v1_me_profile_get / v1_me_profile_put


def test_me_profile_get_happy_path(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.get("/v1/me/profile/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["profile"]["bio"] == ""
    with db.session_scope() as s:
        user = s.get(User, uid)
        assert user.person_id is not None


def test_me_profile_get_user_vanishes_mid_request(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    vanish_user_after(monkeypatch, uid, after_calls=1)
    resp = client.get("/v1/me/profile/")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "sign in required"


def test_me_profile_put_user_vanishes_mid_request(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    vanish_user_after(monkeypatch, uid, after_calls=1)
    resp = client.put("/v1/me/profile/", json={"bio": "hi"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "sign in required"


def test_me_profile_put_requires_json_object(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.put(
        "/v1/me/profile/",
        data="not json",
        content_type="text/plain",
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "JSON object required"


def test_me_profile_put_happy_path_then_updates_existing_row(client):
    """First PUT creates the profile row (profile is None branch); second PUT
    on the same account finds it already exists (profile is not None branch)."""
    uid = add_user()
    sign_in(client, uid)
    resp = client.put(
        "/v1/me/profile/",
        json={"bio": "Hello", "avatarUrl": "https://example.org/a.png", "location": "Here"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["profile"]["bio"] == "Hello"
    with db.session_scope() as s:
        user = s.get(User, uid)
        assert s.get(PersonProfile, user.person_id) is not None

    resp = client.put(
        "/v1/me/profile/",
        json={"bio": "Updated", "visibility": "private"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 200
    body = resp.get_json()["profile"]
    assert body["bio"] == "Updated"
    assert body["visibility"] == "private"
