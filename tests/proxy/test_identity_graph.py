# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for immutable external-account bindings."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, identity_graph, people_index  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    PersonAccountBinding,
    PersonIdentifier,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolhubAccountProjection,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    ToolSummaryCache,
    User,
    utcnow,
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


def canonical_tool(name, *, url="", api_url=""):
    now = utcnow()
    return CanonicalToolCache(
        tool_name=name,
        record={"name": name, "title": name, "url": url, "api_url": api_url},
        source_url=f"https://toolhub.example/api/tools/{name}/",
        expires_at=now,
        stale_until=now,
    )


def test_sul_bound_toolforge_account_joins_the_toolhub_person():
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account())
        session.add(ToolforgeMembershipProjection(uid_number="9001", tool_name="example-tool"))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["verified"] == 1
    assert result["canonicalMembershipRelationships"] == 0
    assert result["fallbackMembershipRelationships"] == 1
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


@pytest.mark.parametrize(
    ("canonical_name", "record_kwargs", "project"),
    [
        ("mix-n-match", {"url": "https://mix-n-match.toolforge.org/"}, "mix-n-match"),
        ("toolforge-cersei", {}, "cersei"),
        (
            "plain-name",
            {"api_url": "https://toolsadmin.wikimedia.org/tools/id/project-from-api/toolinfo/1.2/toolinfo.json"},
            "project-from-api",
        ),
    ],
)
def test_toolforge_memberships_resolve_canonical_tool_aliases(canonical_name, record_kwargs, project):
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account())
        session.add(ToolforgeMembershipProjection(uid_number="9001", tool_name=project))
        session.add(canonical_tool(canonical_name, **record_kwargs))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["canonicalMembershipRelationships"] == 1
    assert result["fallbackMembershipRelationships"] == 0
    with db.session_scope() as session:
        relationship = session.query(ToolPersonRelationship).one()
        assert relationship.tool_name == canonical_name
        evidence = session.query(ToolRelationshipEvidence).filter_by(withdrawn_at=None).one()
        assert evidence.evidence_payload["toolforgeToolName"] == project
        assert evidence.evidence_payload["canonicalToolName"] == canonical_name
        assert evidence.evidence_payload["toolMappingMethod"] == "canonical_project_alias"


def test_one_toolforge_project_can_verify_multiple_canonical_records():
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account())
        session.add(ToolforgeMembershipProjection(uid_number="9001", tool_name="mix-n-match"))
        session.add(canonical_tool("mix-n-match", url="https://mix-n-match.toolforge.org/"))
        session.add(canonical_tool("mm_mixnmatch", url="https://mix-n-match.toolforge.org"))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["canonicalMembershipRelationships"] == 2
    assert result["fallbackMembershipRelationships"] == 0
    with db.session_scope() as session:
        assert {row.tool_name for row in session.query(ToolPersonRelationship)} == {"mix-n-match", "mm_mixnmatch"}


def test_canonical_alias_replaces_old_fallback_and_invalidates_tool_summaries():
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account())
        session.add(ToolforgeMembershipProjection(uid_number="9001", tool_name="mix-n-match"))

    with db.session_scope() as session:
        first = identity_graph.synchronize(session)

    assert first["fallbackMembershipRelationships"] == 1
    with db.session_scope() as session:
        now = utcnow()
        session.add(canonical_tool("mix-n-match", url="https://mix-n-match.toolforge.org/"))
        for name in ("mix-n-match", "toolforge-mix-n-match"):
            session.add(
                ToolSummaryCache(
                    tool_name=name,
                    summary={"toolName": name},
                    expires_at=now,
                    stale_until=now,
                )
            )

    with db.session_scope() as session:
        second = identity_graph.synchronize(session)

    assert second["canonicalMembershipRelationships"] == 1
    assert second["fallbackMembershipRelationships"] == 0
    with db.session_scope() as session:
        assert {row.tool_name for row in session.query(ToolPersonRelationship)} == {"mix-n-match"}
        assert {
            row.tool_name
            for row in session.query(ToolRelationshipEvidence).filter_by(withdrawn_at=None)
        } == {"mix-n-match"}
        assert session.query(ToolSummaryCache).count() == 0


def test_existing_identity_graph_uses_preloaded_fast_path(monkeypatch):
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account())
        identity_graph.synchronize(session)

    monkeypatch.setattr(
        identity_graph.people_index,
        "ensure_official_account_person",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected per-account rebuild")),
    )
    monkeypatch.setattr(
        identity_graph,
        "bind_toolforge_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected per-account rebuild")),
    )
    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["toolhubBindings"] == 2
    assert result["verified"] == 1


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


def test_multiple_developer_accounts_with_one_global_id_join_the_same_person():
    with db.session_scope() as session:
        session.add(toolhub_account())
        session.add(toolforge_account(uid_number="1", uid="one"))
        session.add(toolforge_account(uid_number="2", uid="two"))

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["verified"] == 2
    with db.session_scope() as session:
        bindings = session.query(PersonAccountBinding).filter_by(provider="toolforge").all()
        assert {row.status for row in bindings} == {"verified"}
        assert len({row.person_id for row in bindings}) == 1
        assert {
            row.value
            for row in session.query(PersonIdentifier).filter_by(namespace=people_index.NS_TOOLFORGE_UID_NUMBER)
        } == {"1", "2"}


def test_conflicting_toolhub_and_wikimedia_owners_create_an_account_binding_conflict():
    with db.session_scope() as session:
        toolhub_person = people_index.ensure_person(session, display_name="Toolhub", toolhub_user_id="42")
        wikimedia_person = people_index.ensure_person(
            session,
            display_name="Wikimedia",
            wikimedia_global_user_id="160",
        )
        session.add(toolhub_account())
        toolhub_public_id = toolhub_person.public_id
        wikimedia_public_id = wikimedia_person.public_id

    with db.session_scope() as session:
        result = identity_graph.synchronize(session)

    assert result["toolhubConflicts"] == 1
    with db.session_scope() as session:
        binding = session.query(PersonAccountBinding).filter_by(provider="toolhub", external_id="42").one()
        assert binding.status == "conflict"
        assert binding.person_id is None
        assert binding.evidence["toolhubPersonId"] == toolhub_public_id
        assert binding.evidence["wikimediaPersonId"] == wikimedia_public_id


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


def test_reconciliation_queues_stable_account_binding_conflicts_for_operator_review():
    from backend import people_reconcile  # noqa: PLC0415 - isolated integration assertion

    with db.session_scope() as session:
        people_index.ensure_person(session, display_name="Toolhub", toolhub_user_id="42")
        people_index.ensure_person(session, display_name="Wikimedia", wikimedia_global_user_id="160")
        session.add(toolhub_account())

    with db.session_scope() as session:
        summary = people_reconcile.run(session, mode=people_reconcile.MODE_APPLY)

    assert summary["accountBindingConflictsQueued"] == 1
    assert summary["conflicts"] == 1
