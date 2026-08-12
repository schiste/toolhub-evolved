# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for replay-safe Toolforge account reconnection."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import account_linking, db, identity_graph  # noqa: E402
from backend.models import (  # noqa: E402
    AccountLinkChallenge,
    PersonAccountBinding,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolhubAccountProjection,
    User,
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
