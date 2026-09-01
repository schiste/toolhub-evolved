# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for replay-safe Toolforge account reconnection."""

import sys
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import account_linking, db, identity_graph, people_index  # noqa: E402
from backend.models import (  # noqa: E402
    AccountLinkChallenge,
    PersonAccountBinding,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolhubAccountProjection,
    User,
    utcnow,
)


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def seed() -> int:
    with db.session_scope() as session:
        session.add(
            ToolhubAccountProjection(
                toolhub_user_id="42",
                username="Alice",
                normalized_username="alice",
                wikimedia_global_user_id="160",
            )
        )
        session.add(User(wm_sub="42", username="Alice", wikimedia_global_user_id="160"))
        session.add(
            ToolforgeAccountProjection(
                uid_number="9001",
                uid="alice-dev",
                normalized_uid="alice-dev",
                developer_username="AliceDeveloper",
                normalized_developer_username="alicedeveloper",
                ssh_key_count=1,
            )
        )
        session.add(ToolforgeMembershipProjection(uid_number="9001", tool_name="alice-tool"))
        session.flush()
        return session.query(User).one().id


def test_valid_signature_binds_the_account_once_and_projects_all_memberships():
    user_id = seed()
    with db.session_scope() as session:
        user = session.get(User, user_id)
        started = account_linking.start_toolforge_challenge(session, user, "alice-dev")

    assert started["username"] == "AliceDeveloper"
    assert started["developerUsername"] == "AliceDeveloper"
    assert started["shellUsername"] == "alice-dev"

    with db.session_scope() as session:
        user = session.get(User, user_id)
        completed = account_linking.complete_toolforge_challenge(
            session,
            user,
            challenge_id=started["challengeId"],
            challenge=started["challenge"],
            signature="signed",
            key_loader=lambda uid_number: ["ssh-ed25519 AAAAtest"] if uid_number == "9001" else [],
            verifier=lambda challenge, signature, keys: bool(challenge and signature == "signed" and keys),
        )

    assert completed["status"] == "verified"
    assert completed["proofMethod"] == identity_graph.PROOF_AUTHENTICATED
    with db.session_scope() as session:
        binding = session.query(PersonAccountBinding).filter_by(provider="toolforge").one()
        assert binding.external_id == "9001"
        assert binding.verified_by_user_id == user_id
        challenge = session.get(AccountLinkChallenge, started["challengeId"])
        assert challenge.completed_at is not None
        with pytest.raises(account_linking.AccountLinkError, match="already been used"):
            account_linking.complete_toolforge_challenge(
                session,
                session.get(User, user_id),
                challenge_id=started["challengeId"],
                challenge=started["challenge"],
                signature="signed",
                key_loader=lambda _uid: ["key"],
                verifier=lambda *_args: True,
            )


def test_account_lookup_accepts_developer_and_shell_names_without_conflating_them():
    seed()
    with db.session_scope() as session:
        developer = account_linking._account_by_username(session, "AliceDeveloper")
        shell = account_linking._account_by_username(session, "alice-dev")

    assert developer.uid_number == shell.uid_number == "9001"
    assert developer.developer_username == "AliceDeveloper"
    assert developer.uid == "alice-dev"


def test_modified_challenge_is_rejected_and_attempt_is_counted():
    user_id = seed()
    with db.session_scope() as session:
        started = account_linking.start_toolforge_challenge(session, session.get(User, user_id), "alice-dev")

    with db.session_scope() as session:
        with pytest.raises(account_linking.AccountLinkError, match="does not match"):
            account_linking.complete_toolforge_challenge(
                session,
                session.get(User, user_id),
                challenge_id=started["challengeId"],
                challenge=started["challenge"] + "tampered",
                signature="signed",
                key_loader=lambda _uid: ["key"],
                verifier=lambda *_args: True,
            )

    with db.session_scope() as session:
        assert session.get(AccountLinkChallenge, started["challengeId"]).attempts == 1


def test_link_state_exposes_candidates_and_upstream_repair_paths():
    user_id = seed()
    with db.session_scope() as session:
        identity_graph.synchronize(session)
        user = session.get(User, user_id)
        person = identity_graph.person_for_identifier(session, "toolhub_user_id", "42")
        session.add(
            PersonAccountBinding(
                provider="toolforge",
                external_id="9001",
                person_id=person.id,
                status="candidate",
                proof_method=identity_graph.PROOF_EXACT_HANDLE,
                confidence=70,
            )
        )
        payload = account_linking.link_state(session, user)

    assert payload["proofMethods"]["toolforgeSshSignature"] is True
    assert payload["upstreamRepair"]["profileUrl"].startswith("https://toolsadmin.wikimedia.org/")
    assert payload["candidates"][0]["externalId"] == "9001"
    assert payload["candidates"][0]["toolCount"] == 1
    assert payload["candidates"][0]["sshSignatureAvailable"] is True


def test_account_without_a_published_ssh_key_cannot_start_a_challenge():
    user_id = seed()
    with db.session_scope() as session:
        session.get(ToolforgeAccountProjection, "9001").ssh_key_count = 0
        with pytest.raises(account_linking.AccountLinkError, match="no public SSH key"):
            account_linking.start_toolforge_challenge(session, session.get(User, user_id), "alice-dev")


def test_real_openssh_signature_verifier_accepts_only_the_signed_challenge(tmp_path, monkeypatch):
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        pytest.skip("OpenSSH is unavailable")
    private_key = tmp_path / "identity"
    subprocess.run(
        [keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
        text=True,
    )
    challenge = "toolhub-evolved-account-link-v1\nnonce:test"
    signed = subprocess.run(
        [keygen, "-Y", "sign", "-f", str(private_key), "-n", account_linking.SIGNATURE_NAMESPACE],
        input=challenge,
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.setattr(account_linking, "SSH_KEYGEN", keygen)
    public_key = private_key.with_suffix(".pub").read_text(encoding="utf-8").strip()

    assert account_linking.verify_ssh_signature(challenge, signed.stdout, [public_key]) is True
    assert account_linking.verify_ssh_signature(challenge + "tampered", signed.stdout, [public_key]) is False


def test_account_link_routes_are_private_csrf_protected_and_return_challenges(monkeypatch):
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    user_id = seed()
    client = application.test_client()

    assert client.get("/v1/me/account-links/").status_code == 401
    with client.session_transaction() as browser_session:
        browser_session["uid"] = user_id
        browser_session["csrf"] = "token"
        browser_session["epoch"] = 0
    state = client.get("/v1/me/account-links/")
    assert state.status_code == 200
    assert state.headers["Cache-Control"] == "private, no-store"
    assert (
        client.post(
            "/v1/me/account-links/toolforge/challenges/",
            json={"username": "alice-dev"},
        ).status_code
        == 403
    )
    started = client.post(
        "/v1/me/account-links/toolforge/challenges/",
        json={"username": "alice-dev"},
        headers={"X-CSRF-Token": "token"},
    )
    assert started.status_code == 201
    assert started.get_json()["externalId"] == "9001"

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
    verified = client.post(
        "/v1/me/account-links/toolforge/verify/",
        json={"challengeId": "challenge", "challenge": "value", "signature": "signature"},
        headers={"X-CSRF-Token": "token"},
    )
    assert verified.status_code == 200
    assert verified.get_json()["status"] == "verified"


# ---------------------------------------------------------------------------
# _toolforge_account_summary / link_state edge cases


def test_toolforge_account_summary_returns_empty_dict_for_missing_account():
    with db.session_scope() as session:
        assert account_linking._toolforge_account_summary(session, "does-not-exist") == {}


def test_link_state_skips_candidate_row_with_missing_toolforge_account():
    user_id = seed()
    with db.session_scope() as session:
        user = session.get(User, user_id)
        person = people_index.link_user(session, user)
        session.add(
            PersonAccountBinding(
                provider=identity_graph.PROVIDER_TOOLFORGE,
                external_id="ghost-uid",
                person_id=person.id,
                status=identity_graph.STATUS_CANDIDATE,
                proof_method=identity_graph.PROOF_EXACT_HANDLE,
                confidence=50,
            )
        )
        session.flush()
        payload = account_linking.link_state(session, user)
    assert payload["candidates"] == []


# ---------------------------------------------------------------------------
# _account_by_username / start_toolforge_challenge edge cases


def test_start_toolforge_challenge_unknown_username_raises_account_not_found():
    user_id = seed()
    with db.session_scope() as session:
        with pytest.raises(account_linking.AccountLinkError, match="not found or is ambiguous"):
            account_linking.start_toolforge_challenge(session, session.get(User, user_id), "no-such-user")


def test_start_toolforge_challenge_already_connected_to_same_person():
    user_id = seed()
    with db.session_scope() as session:
        user = session.get(User, user_id)
        person = people_index.link_user(session, user)
        session.add(
            PersonAccountBinding(
                provider=identity_graph.PROVIDER_TOOLFORGE,
                external_id="9001",
                person_id=person.id,
                status=identity_graph.STATUS_VERIFIED,
                proof_method=identity_graph.PROOF_AUTHENTICATED,
                confidence=100,
            )
        )
        session.flush()
        with pytest.raises(account_linking.AccountLinkError, match="already connected"):
            account_linking.start_toolforge_challenge(session, user, "alice-dev")


def test_start_toolforge_challenge_connected_to_another_person():
    user_id = seed()
    with db.session_scope() as session:
        session.add(User(wm_sub="99", username="Bob", wikimedia_global_user_id="161"))
        session.flush()
        other_user = session.query(User).filter_by(wm_sub="99").one()
        other_person = people_index.link_user(session, other_user)
        session.add(
            PersonAccountBinding(
                provider=identity_graph.PROVIDER_TOOLFORGE,
                external_id="9001",
                person_id=other_person.id,
                status=identity_graph.STATUS_VERIFIED,
                proof_method=identity_graph.PROOF_AUTHENTICATED,
                confidence=100,
            )
        )
        session.flush()
        user = session.get(User, user_id)
        with pytest.raises(account_linking.AccountLinkError, match="connected to another person"):
            account_linking.start_toolforge_challenge(session, user, "alice-dev")


# ---------------------------------------------------------------------------
# load_toolforge_ssh_keys


class _FakeLdapEntry:
    def __init__(self, attrs):
        self.entry_attributes_as_dict = attrs


class _FakeLdapConnection:
    def __init__(self, entries):
        self._entries = entries
        self.unbound = False
        self.last_search = None

    def search(self, base_dn, ldap_filter, attributes=None, size_limit=None):
        self.last_search = (base_dn, ldap_filter, attributes, size_limit)

    @property
    def entries(self):
        return self._entries

    def unbind(self):
        self.unbound = True


def _install_fake_ldap(monkeypatch, entries):
    connection = _FakeLdapConnection(entries)
    monkeypatch.setattr(account_linking.public_identity, "Connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(account_linking.public_identity, "Server", lambda *_a, **_k: object())
    monkeypatch.setattr(account_linking.public_identity, "escape_filter_chars", lambda value: value)
    return connection


def test_load_toolforge_ssh_keys_returns_empty_when_ldap_client_unavailable(monkeypatch):
    monkeypatch.setattr(account_linking.public_identity, "Connection", None)
    assert account_linking.load_toolforge_ssh_keys("9001") == []


def test_load_toolforge_ssh_keys_returns_empty_for_non_unique_match(monkeypatch):
    connection = _install_fake_ldap(monkeypatch, [])
    assert account_linking.load_toolforge_ssh_keys("9001") == []
    assert connection.unbound is True


def test_load_toolforge_ssh_keys_returns_empty_when_resolved_uid_mismatches(monkeypatch):
    entry = _FakeLdapEntry({"uidNumber": ["9002"], "sshPublicKey": ["ssh-ed25519 AAAA"]})
    _install_fake_ldap(monkeypatch, [entry])
    assert account_linking.load_toolforge_ssh_keys("9001") == []


def test_load_toolforge_ssh_keys_returns_cleaned_keys_for_exact_match(monkeypatch):
    entry = _FakeLdapEntry({"uidNumber": ["9001"], "sshPublicKey": ["ssh-ed25519 AAAA", "  ", "ssh-rsa BBBB"]})
    connection = _install_fake_ldap(monkeypatch, [entry])
    keys = account_linking.load_toolforge_ssh_keys("9001")
    assert keys == ["ssh-ed25519 AAAA", "ssh-rsa BBBB"]
    assert connection.unbound is True


def test_load_toolforge_ssh_keys_returns_empty_when_keys_attribute_is_not_a_list(monkeypatch):
    entry = _FakeLdapEntry({"uidNumber": "9001", "sshPublicKey": "not-a-list"})
    _install_fake_ldap(monkeypatch, [entry])
    assert account_linking.load_toolforge_ssh_keys("9001") == []


# ---------------------------------------------------------------------------
# verify_ssh_signature edge cases


def test_verify_ssh_signature_rejects_missing_safe_keys_or_bad_prefix():
    assert account_linking.verify_ssh_signature("challenge", "not-a-signature", []) is False
    assert account_linking.verify_ssh_signature("challenge", "not-a-signature", ["ssh-ed25519 AAAA"]) is False


def test_verify_ssh_signature_rejects_oversized_signature_and_missing_ssh_keygen(monkeypatch):
    oversized = "-----BEGIN SSH SIGNATURE-----" + ("A" * account_linking.MAX_SIGNATURE_BYTES)
    assert account_linking.verify_ssh_signature("challenge", oversized, ["ssh-ed25519 AAAA"]) is False

    monkeypatch.setattr(account_linking, "SSH_KEYGEN", "/no/such/ssh-keygen")
    assert (
        account_linking.verify_ssh_signature("challenge", "-----BEGIN SSH SIGNATURE-----short", ["ssh-ed25519 AAAA"])
        is False
    )


# ---------------------------------------------------------------------------
# complete_toolforge_challenge edge cases


def test_complete_toolforge_challenge_unknown_challenge_id_raises():
    user_id = seed()
    with db.session_scope() as session:
        with pytest.raises(account_linking.AccountLinkError, match="was not found"):
            account_linking.complete_toolforge_challenge(
                session,
                session.get(User, user_id),
                challenge_id="does-not-exist",
                challenge="x",
                signature="y",
                key_loader=lambda _uid: [],
                verifier=lambda *_args: True,
            )


def test_complete_toolforge_challenge_expired_raises():
    user_id = seed()
    with db.session_scope() as session:
        started = account_linking.start_toolforge_challenge(session, session.get(User, user_id), "alice-dev")
    with db.session_scope() as session:
        session.get(AccountLinkChallenge, started["challengeId"]).expires_at = utcnow() - timedelta(minutes=1)
    with db.session_scope() as session:
        with pytest.raises(account_linking.AccountLinkError, match="expired"):
            account_linking.complete_toolforge_challenge(
                session,
                session.get(User, user_id),
                challenge_id=started["challengeId"],
                challenge=started["challenge"],
                signature="sig",
                key_loader=lambda _uid: ["key"],
                verifier=lambda *_args: True,
            )


def test_complete_toolforge_challenge_too_many_attempts_raises():
    user_id = seed()
    with db.session_scope() as session:
        started = account_linking.start_toolforge_challenge(session, session.get(User, user_id), "alice-dev")
    with db.session_scope() as session:
        session.get(AccountLinkChallenge, started["challengeId"]).attempts = account_linking.MAX_ATTEMPTS
    with db.session_scope() as session:
        with pytest.raises(account_linking.AccountLinkError, match="too many failed attempts"):
            account_linking.complete_toolforge_challenge(
                session,
                session.get(User, user_id),
                challenge_id=started["challengeId"],
                challenge=started["challenge"],
                signature="sig",
                key_loader=lambda _uid: ["key"],
                verifier=lambda *_args: True,
            )


def test_complete_toolforge_challenge_invalid_signature_increments_attempts():
    user_id = seed()
    with db.session_scope() as session:
        started = account_linking.start_toolforge_challenge(session, session.get(User, user_id), "alice-dev")
    with db.session_scope() as session:
        with pytest.raises(account_linking.AccountLinkError, match="was not valid"):
            account_linking.complete_toolforge_challenge(
                session,
                session.get(User, user_id),
                challenge_id=started["challengeId"],
                challenge=started["challenge"],
                signature="sig",
                key_loader=lambda _uid: ["key"],
                verifier=lambda *_args: False,
            )
    with db.session_scope() as session:
        row = session.get(AccountLinkChallenge, started["challengeId"])
        assert row.attempts == 1
        assert row.last_error == "signature_invalid"


def test_complete_toolforge_challenge_account_unavailable_raises():
    user_id = seed()
    with db.session_scope() as session:
        started = account_linking.start_toolforge_challenge(session, session.get(User, user_id), "alice-dev")
    with db.session_scope() as session:
        session.get(ToolforgeAccountProjection, "9001").disabled = True
    with db.session_scope() as session:
        with pytest.raises(account_linking.AccountLinkError, match="no longer available"):
            account_linking.complete_toolforge_challenge(
                session,
                session.get(User, user_id),
                challenge_id=started["challengeId"],
                challenge=started["challenge"],
                signature="sig",
                key_loader=lambda _uid: ["key"],
                verifier=lambda *_args: True,
            )
