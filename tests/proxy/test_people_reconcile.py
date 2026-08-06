# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic people and evidence reconciliation."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, people_reconcile, sync  # noqa: E402
from backend.author_claims import ToolforgeMembershipProvider  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    Person,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationQueue,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    User,
    utcnow,
)
from backend.people_identity import ToolhubIdentityProvider  # noqa: E402


def _configure() -> None:
    db.configure("sqlite://")
    db.init_schema()


def test_apply_links_account_by_immutable_toolhub_id_and_is_idempotent():
    _configure()
    with db.session_scope() as s:
        user = User(wm_sub="42", username="Alice", wikimedia_global_user_id="160")
        s.add(user)
        s.add(
            CanonicalToolCache(
                tool_name="alias-tool",
                record={
                    "name": "alias-tool",
                    "author": [{"name": "Alice", "developer_username": "Alice", "wiki_username": "AliceWiki"}],
                    "created_by": {"id": 42, "username": "Alice"},
                },
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )
        s.flush()

        dry_summary = people_reconcile.run(s, mode=people_reconcile.MODE_DRY_RUN)
        assert dry_summary["toolsRebuilt"] == 0
        assert s.query(ToolRelationshipEvidence).count() == 0

        apply_summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert apply_summary["toolsRebuilt"] == 1
        assert s.query(Person).count() == 2
        assert s.query(ToolPersonRelationship).count() == 2
        public_ids = {person.public_id for person in s.query(Person)}
        assert user.person_id is not None
        assert {row.namespace for row in s.query(PersonIdentifier)} == {
            "toolforge_username",
            "toolhub_user_id",
            "toolhub_username",
            "wikimedia_global_user_id",
            "wiki_username",
        }

        rerun_summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert rerun_summary["toolsRebuilt"] == 1
        assert {person.public_id for person in s.query(Person)} == public_ids
        assert s.query(ToolPersonRelationship).count() == 2


def test_display_names_remain_non_merging_conflicts():
    _configure()
    with db.session_scope() as s:
        s.add_all(
            [
                Person(canonical_key="display:bob-one", display_name="Bob", identity_quality="display_name"),
                Person(canonical_key="display:bob-two", display_name="Bob", identity_quality="display_name"),
            ]
        )
        s.flush()

        summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)

        assert summary["conflicts"] == 1
        assert s.query(Person).count() == 2
        assert s.query(PersonReconciliationConflict).count() == 1
        conflict = s.query(PersonReconciliationConflict).one()
        assert conflict.status == "pending"
        assert conflict.details["candidateCount"] == 2
        assert conflict.details["unresolvedAttributionCount"] == 2

        people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert s.query(PersonReconciliationConflict).count() == 1


def test_stable_identity_never_adopts_a_unique_display_only_person():
    _configure()
    with db.session_scope() as s:
        display = people_index.ensure_person(s, display_name="Magnus Manske", display_scope="one-observation")
        stable = people_index.ensure_person(
            s,
            display_name="Magnus Manske",
            toolhub_user_id="152",
            toolhub_username="Magnus Manske",
        )

        assert display.id != stable.id
        assert display.identity_quality == "display_name"
        assert stable.identity_quality == "stable"


def test_incremental_queue_deduplicates_and_rebuilds_one_changed_tool():
    _configure()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="queued-tool",
                record={
                    "name": "queued-tool",
                    "author": [{"name": "Queue User", "developer_username": "queue-user"}],
                },
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )

    assert people_reconcile.enqueue_tool_names(["queued-tool", "queued-tool"], reason="canonical_fetch") == 1
    summary = people_reconcile.process_queue(limit=1)

    assert summary == {"claimed": 1, "processed": 1, "failed": 0}
    with db.session_scope() as s:
        assert s.get(PersonReconciliationQueue, "queued-tool") is None
        assert s.query(ToolPersonRelationship).filter_by(tool_name="queued-tool").count() == 1

    assert people_reconcile.process_queue(limit=1) == {"claimed": 0, "processed": 0, "failed": 0}


def test_apply_persists_exact_identity_candidates_without_merging_observations():
    _configure()
    with db.session_scope() as s:
        for tool_name in ("mix-n-match", "other-tool"):
            people_index.replace_source_evidence(
                s,
                tool_name,
                "toolhub_author_metadata",
                [{"display_name": "Magnus Manske", "relationship_type": sync.PERSON_REL_AUTHOR}],
            )
        identity_provider = ToolhubIdentityProvider(
            fetcher=lambda _label: (
                200,
                {
                    "results": [
                        {
                            "id": 152,
                            "username": "Magnus Manske",
                            "social_auth": [{"provider": "wikimedia", "uid": "160"}],
                        }
                    ]
                },
            )
        )
        membership_provider = ToolforgeMembershipProvider(
            lookup=lambda _username: ["cn=tools.mix-n-match,ou=servicegroups,dc=wikimedia,dc=org"]
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_provider=identity_provider,
            membership_provider=membership_provider,
        )

        assert summary["identityCandidatesCreated"] == 2
        mappings = s.query(PersonReconciliationMapping).order_by(PersonReconciliationMapping.confidence.desc()).all()
        assert [row.confidence for row in mappings] == [90, 70]
        assert mappings[0].evidence["matchedToolforgeMemberships"] == ["mix-n-match"]
        assert {row.person_id for row in s.query(ToolRelationshipEvidence)} == {
            row.source_person_id for row in mappings
        }
        target_ids = {row.target_person_id for row in mappings}
        assert len(target_ids) == 1
        target_identifiers = {
            (row.namespace, row.value)
            for row in s.query(PersonIdentifier).filter(PersonIdentifier.person_id.in_(target_ids))
        }
        assert target_identifiers == {
            ("toolforge_username", "Magnus Manske"),
            ("toolhub_user_id", "152"),
            ("toolhub_username", "Magnus Manske"),
            ("wikimedia_global_user_id", "160"),
        }

        rerun = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_provider=identity_provider,
            membership_provider=membership_provider,
        )
        assert rerun["identityCandidatesCreated"] == 0
        assert s.query(PersonReconciliationMapping).count() == 2


def test_conflicting_cross_system_stable_ids_queue_conflict_and_never_merge():
    _configure()
    with db.session_scope() as s:
        toolhub_person = people_index.ensure_person(s, display_name="First", toolhub_user_id="152")
        wikimedia_person = people_index.ensure_person(s, display_name="Second", wikimedia_global_user_id="160")
        people_index.replace_source_evidence(
            s,
            "ambiguous-tool",
            "source",
            [{"display_name": "Magnus Manske", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        provider = ToolhubIdentityProvider(
            fetcher=lambda _label: (
                200,
                {
                    "results": [
                        {
                            "id": 152,
                            "username": "Magnus Manske",
                            "social_auth": [{"provider": "wikimedia", "uid": "160"}],
                        }
                    ]
                },
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_provider=provider,
            membership_provider=ToolforgeMembershipProvider(lookup=lambda _username: []),
        )

        assert summary["identityCandidatesCreated"] == 0
        assert summary["stableIdentityConflicts"] == 1
        assert s.query(PersonReconciliationMapping).count() == 0
        conflict = (
            s.query(PersonReconciliationConflict)
            .filter_by(conflict_type="conflicting_stable_identifiers")
            .one()
        )
        assert conflict.details["toolhubPersonId"] == toolhub_person.public_id
        assert conflict.details["wikimediaPersonId"] == wikimedia_person.public_id
        assert toolhub_person.id != wikimedia_person.id
