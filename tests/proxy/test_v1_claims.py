# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_claims.py: the /v1/claims/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it. Claim and challenge rows are inserted directly through the ORM so each
test can drive one specific branch of the verify/revoke handlers.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
import backend.v1_claims as v1_claims_api  # noqa: E402
from backend import authz, db, security, sync, toolinfo_control  # noqa: E402
from backend.models import (  # noqa: E402
    ToolAuthorClaim,
    ToolinfoControlChallenge,
    User,
    utcnow,
)


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


def make_claim(
    *,
    tool_name,
    author_name="Ada Lovelace",
    toolhub_username="Ada",
    user_id=None,
    method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    status=sync.AUTHOR_CLAIM_UNVERIFIED,
    revoked_at=None,
    evidence_url=None,
    evidence_payload=None,
):
    with db.session_scope() as s:
        row = ToolAuthorClaim(
            tool_name=tool_name,
            author_name=author_name,
            toolhub_username=toolhub_username,
            user_id=user_id,
            verification_status=status,
            verification_method=method,
            requested_relationship=sync.PERSON_REL_AUTHOR,
            evidence_url=evidence_url,
            evidence_payload=evidence_payload,
            revoked_at=revoked_at,
        )
        s.add(row)
        s.flush()
        return row.id


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


class FakeProvider:
    """Stand-in for ToolforgeMaintainerProvider / SignedToolinfoProvider."""

    def __init__(self, rows=None, exc=None):
        self.rows = rows if rows is not None else []
        self.exc = exc
        self.calls = []

    def verify(self, s, user, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.rows


def verify(client, claim_id):
    return client.post(f"/v1/claims/{claim_id}/verify/", headers={"X-CSRF-Token": "tok"})


def revoke(client, claim_id):
    return client.delete(f"/v1/claims/{claim_id}/", headers={"X-CSRF-Token": "tok"})


# ---------------------------------------------------------------------------
# v1_claim_verify


def test_verify_claim_not_found(client):
    uid = add_user()
    sign_in(client, uid)
    resp = verify(client, 999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "claim not found"


def test_verify_claim_revoked(client):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(tool_name="alpha-revoked", user_id=uid, revoked_at=utcnow())
    resp = verify(client, claim_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "revoked claims cannot be verified"


def test_verify_claim_author_display_name_cannot_self_verify(client):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-display",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    )
    resp = verify(client, claim_id)
    assert resp.status_code == 409
    assert "identity evidence" in resp.get_json()["error"]


def test_verify_claim_toolhub_write_access_is_automatic(client):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-write-access",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    )
    resp = verify(client, claim_id)
    assert resp.status_code == 409
    assert "verified automatically" in resp.get_json()["error"]


def test_verify_toolinfo_url_control_missing_challenge_id(client):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-control-noid",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload=None,  # not a dict -> {} -> no challengeId
    )
    resp = verify(client, claim_id)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "claim challenge not found"


def test_verify_toolinfo_url_control_challenge_missing_row(client):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-control-missing",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": 999999},
    )
    resp = verify(client, claim_id)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "claim challenge not found"


def test_verify_toolinfo_url_control_challenge_owned_by_someone_else(client):
    uid = add_user("Ada", "42")
    other_uid = add_user("Bob", "43")
    sign_in(client, uid)
    challenge_id = make_challenge(user_id=other_uid, tool_name="alpha-control-other")
    claim_id = make_claim(
        tool_name="alpha-control-other",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": challenge_id},
    )
    resp = verify(client, claim_id)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "claim challenge not found"


def test_verify_toolinfo_url_control_challenge_expired_returns_error(client):
    uid = add_user()
    sign_in(client, uid)
    challenge_id = make_challenge(
        user_id=uid,
        tool_name="alpha-control-expired",
        status=toolinfo_control.CHALLENGE_STATUS_PENDING,
        expires_in=timedelta(hours=-1),
    )
    claim_id = make_claim(
        tool_name="alpha-control-expired",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": challenge_id},
    )
    resp = verify(client, claim_id)
    assert resp.status_code == 409
    assert "expired" in resp.get_json()["error"]


def test_verify_toolinfo_url_control_already_verified_succeeds(client):
    uid = add_user()
    sign_in(client, uid)
    challenge_id = make_challenge(
        user_id=uid,
        tool_name="alpha-control-ok",
        status=toolinfo_control.CHALLENGE_STATUS_VERIFIED,
    )
    claim_id = make_claim(
        tool_name="alpha-control-ok",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": challenge_id},
    )
    resp = verify(client, claim_id)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["claim"]["verificationStatus"] == sync.AUTHOR_CLAIM_VERIFIED
    assert body["challenge"]["status"] == toolinfo_control.CHALLENGE_STATUS_VERIFIED


def test_verify_claim_tool_lookup_error(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-tool-missing",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    )
    monkeypatch.setattr(v1_claims_api.common, "claim_tool_or_error", lambda name: (None, v1_claims_api.common.bad("nope")))
    resp = verify(client, claim_id)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "nope"


def test_verify_claim_toolforge_maintainer_with_rows(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-forge-rows",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    )
    tool = {"name": "alpha-forge-rows"}
    monkeypatch.setattr(v1_claims_api.common, "claim_tool_or_error", lambda name: (tool, None))
    fake = FakeProvider(rows=[])
    monkeypatch.setattr(v1_api, "TOOLFORGE_MAINTAINER_PROVIDER", fake)
    resp = verify(client, claim_id)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    # rows was empty -> falls back to the original row
    assert body["claim"]["id"] == claim_id
    assert fake.calls[0]["tool_name"] == "alpha-forge-rows"


def test_verify_claim_toolforge_maintainer_returns_new_row(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-forge-newrow",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    )
    other_claim_id = make_claim(
        tool_name="alpha-forge-newrow-2",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
    )
    tool = {"name": "alpha-forge-newrow"}
    monkeypatch.setattr(v1_claims_api.common, "claim_tool_or_error", lambda name: (tool, None))
    with db.session_scope() as s:
        replacement = s.get(ToolAuthorClaim, other_claim_id)
        fake = FakeProvider(rows=[replacement])
    monkeypatch.setattr(v1_api, "TOOLFORGE_MAINTAINER_PROVIDER", fake)
    resp = verify(client, claim_id)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["claim"]["id"] == other_claim_id


def test_verify_claim_signed_toolinfo_fetch_failure(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-signed-fail",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
        evidence_url="https://example.org/toolinfo.json",
    )
    tool = {"name": "alpha-signed-fail"}
    monkeypatch.setattr(v1_claims_api.common, "claim_tool_or_error", lambda name: (tool, None))

    def boom(url, tool_name):
        message = "fetch exploded"
        raise ValueError(message)

    monkeypatch.setattr(v1_claims_api, "fetch_matching_item", boom)
    resp = verify(client, claim_id)
    assert resp.status_code == 400
    assert "Could not read signed toolinfo" in resp.get_json()["error"]


def test_verify_claim_signed_toolinfo_success_with_rows(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-signed-ok",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
        evidence_url="https://example.org/toolinfo.json",
    )
    tool = {"name": "alpha-signed-ok"}
    monkeypatch.setattr(v1_claims_api.common, "claim_tool_or_error", lambda name: (tool, None))
    monkeypatch.setattr(v1_claims_api, "fetch_matching_item", lambda url, tool_name: {"name": tool_name})
    with db.session_scope() as s:
        row = s.get(ToolAuthorClaim, claim_id)
        fake = FakeProvider(rows=[row])
    monkeypatch.setattr(v1_api, "SIGNED_TOOLINFO_PROVIDER", fake)
    resp = verify(client, claim_id)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["claim"]["id"] == claim_id
    assert fake.calls[0]["evidence_url"] == "https://example.org/toolinfo.json"


def test_verify_claim_signed_toolinfo_no_rows_keeps_original(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-signed-norows",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
        evidence_url="https://example.org/toolinfo.json",
    )
    tool = {"name": "alpha-signed-norows"}
    monkeypatch.setattr(v1_claims_api.common, "claim_tool_or_error", lambda name: (tool, None))
    monkeypatch.setattr(v1_claims_api, "fetch_matching_item", lambda url, tool_name: {"name": tool_name})
    fake = FakeProvider(rows=[])
    monkeypatch.setattr(v1_api, "SIGNED_TOOLINFO_PROVIDER", fake)
    resp = verify(client, claim_id)
    assert resp.status_code == 200
    assert resp.get_json()["claim"]["id"] == claim_id


def test_verify_claim_unsupported_method(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-bogus",
        user_id=uid,
        method="not-a-real-method",
    )
    tool = {"name": "alpha-bogus"}
    monkeypatch.setattr(v1_claims_api.common, "claim_tool_or_error", lambda name: (tool, None))
    resp = verify(client, claim_id)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unsupported claim method"


# ---------------------------------------------------------------------------
# v1_claim_revoke


def test_revoke_claim_not_found(client):
    uid = add_user()
    sign_in(client, uid)
    resp = revoke(client, 999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "claim not found"


def test_revoke_claim_without_pending_challenge(client):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(tool_name="alpha-revoke-simple", user_id=uid)
    resp = revoke(client, claim_id)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["claim"]["verificationStatus"] == sync.AUTHOR_CLAIM_REVOKED
    assert body["claim"]["revokedAt"]


def test_revoke_claim_with_missing_challenge_row(client):
    uid = add_user()
    sign_in(client, uid)
    claim_id = make_claim(
        tool_name="alpha-revoke-noid",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": 424242},
    )
    resp = revoke(client, claim_id)
    assert resp.status_code == 200
    with db.session_scope() as s:
        row = s.get(ToolAuthorClaim, claim_id)
        assert row.revoked_at is not None


def test_revoke_claim_expires_pending_challenge_owned_by_user(client):
    uid = add_user()
    sign_in(client, uid)
    challenge_id = make_challenge(
        user_id=uid,
        tool_name="alpha-revoke-pending",
        status=toolinfo_control.CHALLENGE_STATUS_PENDING,
    )
    claim_id = make_claim(
        tool_name="alpha-revoke-pending",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": challenge_id},
    )
    resp = revoke(client, claim_id)
    assert resp.status_code == 200
    with db.session_scope() as s:
        challenge = s.get(ToolinfoControlChallenge, challenge_id)
        assert challenge.status == toolinfo_control.CHALLENGE_STATUS_EXPIRED


def test_revoke_claim_does_not_touch_already_verified_challenge(client):
    uid = add_user()
    sign_in(client, uid)
    challenge_id = make_challenge(
        user_id=uid,
        tool_name="alpha-revoke-verified",
        status=toolinfo_control.CHALLENGE_STATUS_VERIFIED,
    )
    claim_id = make_claim(
        tool_name="alpha-revoke-verified",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": challenge_id},
    )
    resp = revoke(client, claim_id)
    assert resp.status_code == 200
    with db.session_scope() as s:
        challenge = s.get(ToolinfoControlChallenge, challenge_id)
        assert challenge.status == toolinfo_control.CHALLENGE_STATUS_VERIFIED


def test_revoke_claim_ignores_challenge_owned_by_someone_else(client):
    uid = add_user("Ada", "42")
    other_uid = add_user("Bob", "43")
    sign_in(client, uid)
    challenge_id = make_challenge(
        user_id=other_uid,
        tool_name="alpha-revoke-otherowner",
        status=toolinfo_control.CHALLENGE_STATUS_PENDING,
    )
    claim_id = make_claim(
        tool_name="alpha-revoke-otherowner",
        user_id=uid,
        method=sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_payload={"challengeId": challenge_id},
    )
    resp = revoke(client, claim_id)
    assert resp.status_code == 200
    with db.session_scope() as s:
        challenge = s.get(ToolinfoControlChallenge, challenge_id)
        assert challenge.status == toolinfo_control.CHALLENGE_STATUS_PENDING
