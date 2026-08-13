# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_toolinfo.py: the /v1/toolinfo/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it. Toolinfo network fetches are always monkeypatched away.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1_toolinfo as v1_toolinfo_api  # noqa: E402
from backend import authz, db, security, toolinfo_control  # noqa: E402
from backend.models import ToolinfoControlChallenge, User, utcnow  # noqa: E402


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


def make_challenge(
    *,
    user_id,
    tool_name,
    toolinfo_url="https://example.org/toolinfo.json",
    status=toolinfo_control.CHALLENGE_STATUS_PENDING,
    expires_in=timedelta(hours=1),
    token="issued-token",
):
    with db.session_scope() as s:
        row = ToolinfoControlChallenge(
            user_id=user_id,
            tool_name=tool_name,
            toolinfo_url=toolinfo_url,
            challenge_token=token,
            status=status,
            expires_at=utcnow() + expires_in,
        )
        s.add(row)
        s.flush()
        return row.id


# ---------------------------------------------------------------------------
# v1_toolinfo_control_challenges (GET list)


def test_control_challenges_requires_login(client):
    assert client.get("/v1/toolinfo/ownership-challenges/").status_code == 401


def test_control_challenges_lists_and_expires_stale_pending_rows(client):
    uid = add_user()
    other_uid = add_user(username="Bob", wm_sub="43")
    sign_in(client, uid)
    verified_id = make_challenge(
        user_id=uid, tool_name="verified-tool", status=toolinfo_control.CHALLENGE_STATUS_VERIFIED
    )
    fresh_id = make_challenge(
        user_id=uid,
        tool_name="fresh-tool",
        status=toolinfo_control.CHALLENGE_STATUS_PENDING,
        expires_in=timedelta(hours=1),
    )
    stale_id = make_challenge(
        user_id=uid,
        tool_name="stale-tool",
        status=toolinfo_control.CHALLENGE_STATUS_PENDING,
        expires_in=timedelta(hours=-1),
    )
    # Belongs to someone else -> must not appear in this account's list.
    make_challenge(user_id=other_uid, tool_name="other-tool")

    resp = client.get("/v1/toolinfo/ownership-challenges/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["field"] == toolinfo_control.CHALLENGE_FIELD
    by_id = {row["id"]: row for row in body["challenges"]}
    assert set(by_id) == {verified_id, fresh_id, stale_id}
    assert by_id[verified_id]["status"] == toolinfo_control.CHALLENGE_STATUS_VERIFIED
    assert by_id[fresh_id]["status"] == toolinfo_control.CHALLENGE_STATUS_PENDING
    # The stale pending row is flipped to expired as part of serving the list.
    assert by_id[stale_id]["status"] == toolinfo_control.CHALLENGE_STATUS_EXPIRED
    with db.session_scope() as s:
        assert s.get(ToolinfoControlChallenge, stale_id).status == toolinfo_control.CHALLENGE_STATUS_EXPIRED


# ---------------------------------------------------------------------------
# v1_toolinfo_control_challenge_create (POST create)


def test_control_challenge_create_bad_body(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/toolinfo/ownership-challenges/", data="not json", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "body must be a JSON object"


def test_control_challenge_create_requires_tool_name(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/toolinfo/ownership-challenges/",
        json={"toolName": "   ", "toolinfoUrl": "https://example.org/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "toolName is required"


def test_control_challenge_create_propagates_challenge_error(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/toolinfo/ownership-challenges/",
        json={"toolName": "ada-tool", "toolinfoUrl": "not a url"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["validationErrors"][0]["field"] == "toolinfoUrl"
    with db.session_scope() as s:
        assert s.query(ToolinfoControlChallenge).count() == 0


# ---------------------------------------------------------------------------
# v1_toolinfo_control_challenge_verify (POST verify)


def test_control_challenge_verify_not_found(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/toolinfo/ownership-challenges/999999/verify/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "ownership challenge not found"


def test_control_challenge_verify_owned_by_someone_else_is_not_found(client):
    uid = add_user(username="Ada", wm_sub="42")
    other_uid = add_user(username="Bob", wm_sub="43")
    sign_in(client, uid)
    challenge_id = make_challenge(user_id=other_uid, tool_name="other-tool")
    resp = client.post(f"/v1/toolinfo/ownership-challenges/{challenge_id}/verify/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "ownership challenge not found"
