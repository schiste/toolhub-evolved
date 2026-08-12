# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for immutable external-account bindings."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, identity_graph, people_index  # noqa: E402
from backend.models import (  # noqa: E402
    PersonAccountBinding,
    PersonIdentifier,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolhubAccountProjection,
    ToolPersonRelationship,
    User,
)


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def toolhub_account(user_id="42", username="Alice", global_id="160"):
    return ToolhubAccountProjection(
        toolhub_user_id=user_id,
        username=username,
        normalized_username=username.casefold(),
        wikimedia_global_user_id=global_id or None,
    )


def toolforge_account(uid_number="9001", uid="alice", global_id="160"):
    return ToolforgeAccountProjection(
        uid_number=uid_number,
        uid=uid,
        normalized_uid=uid.casefold(),
        wikimedia_global_user_id=global_id or None,
        wikimedia_global_name="Alice" if global_id else "",
    )


def test_sul_bound_toolforge_account_joins_the_toolhub_person():
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account())
        session.add(ToolforgeMembershipProjection(uid_number="9001", tool_name="example-tool"))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["verified"] == 1
    with db.session_scope() as session:
        binding = session.query(PersonAccountBinding).filter_by(provider="toolforge").one()
        assert binding.status == "verified"
        identifiers = {
            (row.namespace, row.value)
            for row in session.query(PersonIdentifier).filter_by(person_id=binding.person_id, is_current=True)
        }
        assert (people_index.NS_TOOLHUB_USER_ID, "42") in identifiers
        assert (people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, "160") in identifiers
        assert (people_index.NS_TOOLFORGE_UID_NUMBER, "9001") in identifiers
        assert (people_index.NS_TOOLFORGE_USERNAME, "alice") in identifiers
        relationship = session.query(ToolPersonRelationship).one()
        assert relationship.tool_name == "toolforge-example-tool"
        assert relationship.relationship_type == "maintainer"
        assert relationship.verification_status == "verified"
        assert relationship.confidence == 100


def test_unbound_matching_handle_is_only_a_candidate():
    with db.session_scope() as session:
        session.add(toolhub_account(username="Alice", global_id="160"))
        session.add(toolforge_account(uid="Alice", global_id=""))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["candidate"] == 1
    with db.session_scope() as session:
        binding = session.query(PersonAccountBinding).filter_by(provider="toolforge").one()
        assert binding.status == "candidate"
        assert binding.confidence == 70
        assert (
            session.query(PersonIdentifier)
            .filter_by(namespace=people_index.NS_TOOLFORGE_UID_NUMBER, value="9001")
            .count()
            == 0
        )


def test_duplicate_global_id_is_a_conflict_and_never_attaches_identifiers():
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account(uid_number="1", uid="one"))
        session.add(toolforge_account(uid_number="2", uid="two"))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["conflict"] == 2
    with db.session_scope() as session:
        assert {row.status for row in session.query(PersonAccountBinding).filter_by(provider="toolforge")} == {
            "conflict"
        }
        assert session.query(PersonIdentifier).filter_by(namespace=people_index.NS_TOOLFORGE_UID_NUMBER).count() == 0


def test_official_projection_hydrates_local_oauth_user_identity():
    with db.session_scope() as session:
        session.add(toolhub_account(user_id="2039", username="Schiste", global_id="6978"))
        session.add(User(wm_sub="2039", username="Schiste", wikimedia_global_user_id=None))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["usersHydrated"] >= 1
    with db.session_scope() as session:
        user = session.query(User).one()
        assert user.wikimedia_global_user_id == "6978"
        assert user.person_id is not None


def test_explicit_verified_binding_rejects_a_stable_identifier_collision():
    with db.session_scope() as session:
        first = people_index.ensure_person(session, display_name="First", toolforge_uid_number="9001")
        second = people_index.ensure_person(session, display_name="Second", toolhub_user_id="2")
        account = toolforge_account(uid_number="9001", global_id="")
        session.add(account)
        session.flush()
        with pytest.raises(identity_graph.IdentityBindingConflictError):
            identity_graph.bind_toolforge_account(
                session,
                account=account,
                person=second,
                proof_method=identity_graph.PROOF_OPERATOR,
                confidence=100,
                evidence={"reviewed": True},
            )
        assert first.id != second.id


def test_reconciliation_runs_account_binding_service_for_all_projections():
    from backend import people_reconcile  # noqa: PLC0415 - isolated integration assertion

    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account())

    with db.session_scope() as session:
        summary = people_reconcile.run(session, mode=people_reconcile.MODE_APPLY)

    assert summary["accountBindings"]["verified"] == 1
