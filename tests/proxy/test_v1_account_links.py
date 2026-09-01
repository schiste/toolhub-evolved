# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_account_links.py: the /v1/me/account-links/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs in
test users the same way tests/proxy/test_v1_claims.py does, without importing from
it. The auth-check branches inside the view bodies (as opposed to the
login_required/write_guard decorators that wrap them) can only be reached when the
decorator's current_user_id() call and the view's own current_user_id() call
disagree, so several tests monkeypatch the view module's imported reference
independently from backend.security's.
"""

import contextlib
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1_account_links as v1_account_links_api  # noqa: E402
from backend import account_linking, db, identity_graph, security  # noqa: E402
from backend.models import ToolforgeAccountProjection, ToolhubAccountProjection, User  # noqa: E402


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def seed_user(username="Alice", wm_sub="42", wikimedia_global_user_id="160"):
    with db.session_scope() as session:
        session.add(
            ToolhubAccountProjection(
                toolhub_user_id=wm_sub,
                username=username,
                normalized_username=username.lower(),
                wikimedia_global_user_id=wikimedia_global_user_id,
            )
        )
        session.add(User(wm_sub=wm_sub, username=username, wikimedia_global_user_id=wikimedia_global_user_id))
        session.flush()
        return session.query(User).filter_by(wm_sub=wm_sub).one().id


def seed_toolforge_account(
    uid_number="9001",
    uid="alice-dev",
    developer_username="AliceDeveloper",
    ssh_key_count=1,
):
    with db.session_scope() as session:
        session.add(
            ToolforgeAccountProjection(
                uid_number=uid_number,
                uid=uid,
                normalized_uid=uid.lower(),
                developer_username=developer_username,
                normalized_developer_username=developer_username.casefold(),
                ssh_key_count=ssh_key_count,
            )
        )


def sign_in(client, uid, csrf="tok"):
    with db.session_scope() as s:
        user = s.get(User, uid)
        epoch = user.session_epoch or 0 if user is not None else 0
    with client.session_transaction() as sess:
        sess["uid"] = uid
        sess["csrf"] = csrf
        sess["epoch"] = epoch


class _DbWithPatchedSessionScope:
    """Delegates every attribute to the real `backend.db` module except session_scope.

    Only patched onto `v1_account_links`'s own `db` name, so it does not disturb
    backend.security's independent `db.session_scope()` calls (e.g. the
    login_required/write_guard epoch check), which keep using the real module.
    """

    def __init__(self, scope_factory):
        self._scope_factory = scope_factory

    def session_scope(self):
        return self._scope_factory()

    def __getattr__(self, name):
        return getattr(db, name)


def _scope_raises_after_success(error_message):
    @contextlib.contextmanager
    def factory():
        with db.session_scope() as session:
            yield session
        raise account_linking.AccountLinkError(error_message)

    return factory


# ---------------------------------------------------------------------------
# GET /v1/me/account-links/


def test_account_links_get_requires_sign_in(client):
    resp = client.get("/v1/me/account-links/")
    assert resp.status_code == 401


def test_account_links_get_internal_auth_check_rejects_when_session_disagrees(client, monkeypatch):
    """Decorator sees a signed-in user, but the view's own check fails (line 16-18, 34-35)."""
    uid = seed_user()
    sign_in(client, uid)
    monkeypatch.setattr(v1_account_links_api, "current_user_id", lambda: None)
    resp = client.get("/v1/me/account-links/")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "sign in required"


def test_account_links_get_returns_sign_in_required_when_user_row_is_missing(client, monkeypatch):
    """Decorator and view both see a uid, but no such User row exists (line 38-39)."""
    monkeypatch.setattr(security, "current_user_id", lambda: 999999)
    monkeypatch.setattr(v1_account_links_api, "current_user_id", lambda: 999999)
    resp = client.get("/v1/me/account-links/")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "sign in required"


def test_account_links_get_returns_state_for_signed_in_user(client):
    uid = seed_user()
    sign_in(client, uid)
    resp = client.get("/v1/me/account-links/")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "private, no-store"
    body = resp.get_json()
    assert body["bindings"] == []
    assert body["candidates"] == []


# ---------------------------------------------------------------------------
# POST /v1/me/account-links/toolforge/challenges/


def test_account_link_challenge_create_requires_sign_in(client):
    resp = client.post("/v1/me/account-links/toolforge/challenges/", json={"username": "alice-dev"})
    assert resp.status_code == 401


def test_account_link_challenge_create_internal_auth_check_rejects_when_session_disagrees(client, monkeypatch):
    uid = seed_user()
    sign_in(client, uid)
    monkeypatch.setattr(v1_account_links_api, "current_user_id", lambda: None)
    resp = client.post(
        "/v1/me/account-links/toolforge/challenges/",
        json={"username": "alice-dev"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "sign in required"


def test_account_link_challenge_create_rejects_non_dict_payload(client):
    uid = seed_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/me/account-links/toolforge/challenges/",
        data="[]",
        content_type="application/json",
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "JSON object required"


def test_account_link_challenge_create_returns_sign_in_required_when_user_row_is_missing(client, monkeypatch):
    monkeypatch.setattr(security, "current_user_id", lambda: 999999)
    monkeypatch.setattr(v1_account_links_api, "current_user_id", lambda: 999999)
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    resp = client.post(
        "/v1/me/account-links/toolforge/challenges/",
        json={"username": "alice-dev"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "sign in required"


def test_account_link_challenge_create_reports_account_link_error_from_inner_call(client):
    uid = seed_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/me/account-links/toolforge/challenges/",
        json={"username": "no-such-toolforge-account"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert "not found" in resp.get_json()["error"]


def test_account_link_challenge_create_succeeds(client):
    uid = seed_user()
    seed_toolforge_account()
    sign_in(client, uid)
    resp = client.post(
        "/v1/me/account-links/toolforge/challenges/",
        json={"username": "alice-dev"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 201
    assert resp.headers["Cache-Control"] == "private, no-store"
    body = resp.get_json()
    assert body["externalId"] == "9001"
    assert body["provider"] == "toolforge"
    assert body["username"] == "AliceDeveloper"
    assert body["developerUsername"] == "AliceDeveloper"
    assert body["shellUsername"] == "alice-dev"


def test_account_link_challenge_create_outer_except_catches_late_session_failure(client, monkeypatch):
    uid = seed_user()
    seed_toolforge_account()
    sign_in(client, uid)
    monkeypatch.setattr(
        v1_account_links_api,
        "db",
        _DbWithPatchedSessionScope(_scope_raises_after_success("boom-after-commit")),
    )
    resp = client.post(
        "/v1/me/account-links/toolforge/challenges/",
        json={"username": "alice-dev"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "boom-after-commit"


# ---------------------------------------------------------------------------
# POST /v1/me/account-links/toolforge/verify/


def test_account_link_challenge_verify_requires_sign_in(client):
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "x", "challenge": "y", "signature": "z"},
    )
    assert resp.status_code == 401


def test_account_link_challenge_verify_internal_auth_check_rejects_when_session_disagrees(client, monkeypatch):
    uid = seed_user()
    sign_in(client, uid)
    monkeypatch.setattr(v1_account_links_api, "current_user_id", lambda: None)
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "x", "challenge": "y", "signature": "z"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "sign in required"


def test_account_link_challenge_verify_rejects_non_dict_payload(client):
    uid = seed_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        data="not-json-object",
        content_type="application/json",
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "JSON object required"


def test_account_link_challenge_verify_returns_sign_in_required_when_user_row_is_missing(client, monkeypatch):
    monkeypatch.setattr(security, "current_user_id", lambda: 999999)
    monkeypatch.setattr(v1_account_links_api, "current_user_id", lambda: 999999)
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "x", "challenge": "y", "signature": "z"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "sign in required"


def test_account_link_challenge_verify_reports_account_link_error_from_inner_call(client):
    uid = seed_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "does-not-exist", "challenge": "y", "signature": "z"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert "was not found" in resp.get_json()["error"]


def test_account_link_challenge_verify_reports_identity_binding_conflict_from_inner_call(client, monkeypatch):
    uid = seed_user()
    sign_in(client, uid)
    monkeypatch.setattr(
        account_linking,
        "complete_toolforge_challenge",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            identity_graph.IdentityBindingConflictError("account belongs to another person")
        ),
    )
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "x", "challenge": "y", "signature": "z"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "account belongs to another person"


def test_account_link_challenge_verify_succeeds(client, monkeypatch):
    uid = seed_user()
    sign_in(client, uid)
    monkeypatch.setattr(
        account_linking,
        "complete_toolforge_challenge",
        lambda *_args, **_kwargs: {
            "ok": True,
            "provider": "toolforge",
            "externalId": "9001",
            "status": "verified",
            "proofMethod": identity_graph.PROOF_AUTHENTICATED,
        },
    )
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "x", "challenge": "y", "signature": "z"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "private, no-store"
    assert resp.get_json()["status"] == "verified"


def test_account_link_challenge_verify_outer_except_catches_late_session_failure(client, monkeypatch):
    uid = seed_user()
    sign_in(client, uid)
    monkeypatch.setattr(
        account_linking,
        "complete_toolforge_challenge",
        lambda *_args, **_kwargs: {
            "ok": True,
            "provider": "toolforge",
            "externalId": "9001",
            "status": "verified",
            "proofMethod": identity_graph.PROOF_AUTHENTICATED,
        },
    )
    monkeypatch.setattr(
        v1_account_links_api,
        "db",
        _DbWithPatchedSessionScope(_scope_raises_after_success("boom-after-commit")),
    )
    resp = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "x", "challenge": "y", "signature": "z"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "boom-after-commit"
