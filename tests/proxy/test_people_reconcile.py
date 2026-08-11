# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic people and evidence reconciliation."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, people_reconcile, sync  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    Person,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationQueue,
    PersonReconciliationRun,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    ToolhubAccountProjection,
    User,
    utcnow,
)
from backend.public_identity import (  # noqa: E402
    PublicIdentityResolver,
    ToolforgeIdentityProvider,
    WikimediaIdentityProvider,
)


def _identity_resolver(*tool_names):
    return PublicIdentityResolver(
        wikimedia=WikimediaIdentityProvider(
            fetcher=lambda _id: (
                200,
                {"query": {"globaluserinfo": {"id": 160, "name": "Magnus Manske"}}},
            )
        ),
        toolforge=ToolforgeIdentityProvider(
            lookup=lambda _username: [
                {
                    "uid": ["magnus"],
                    "uidNumber": ["3067"],
                    "wikimediaGlobalAccountId": ["160"],
                    "wikimediaGlobalAccountName": ["Magnus Manske"],
                    "memberOf": [f"cn=tools.{name},ou=servicegroups,dc=wikimedia,dc=org" for name in tool_names],
                }
            ]
        ),
    )


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


def test_display_names_remain_non_merging_audit_clusters():
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

        assert summary["conflicts"] == 0
        assert summary["ambiguousDisplayNameClusters"] == 1
        assert s.query(Person).count() == 2
        assert s.query(PersonReconciliationConflict).count() == 0

        people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert s.query(PersonReconciliationConflict).count() == 0


def test_reconciliation_retires_legacy_display_conflict_rows():
    _configure()
    with db.session_scope() as s:
        s.add_all(
            [
                Person(canonical_key="display:bob-one", display_name="Bob", identity_quality="display_name"),
                Person(canonical_key="display:bob-two", display_name="Bob", identity_quality="display_name"),
            ]
        )
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        s.add_all(
            [
                PersonReconciliationConflict(
                    run_id=run.id,
                    conflict_type="ambiguous_display_name",
                    value="bob",
                    details={"legacy": True},
                ),
                PersonReconciliationConflict(
                    run_id=run.id,
                    conflict_type="ambiguous_display_name",
                    value="bob",
                    details={"legacy": True},
                ),
            ]
        )

        summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)

        assert summary["nonActionableConflictsRetired"] == 2
        assert summary["conflicts"] == 0
        conflicts = s.query(PersonReconciliationConflict).order_by(PersonReconciliationConflict.id).all()
        assert [row.status for row in conflicts] == ["dismissed", "dismissed"]
        assert all("evidence clusters" in row.review_notes for row in conflicts)


def test_reconciliation_repairs_stale_quality_without_publishing_untrusted_handles():
    _configure()
    with db.session_scope() as s:
        person = Person(
            canonical_key="toolforge:magnus-manske",
            display_name="Magnus Manske",
            identity_quality="stable",
        )
        s.add(person)
        s.flush()
        s.add(
            PersonIdentifier(
                person_id=person.id,
                namespace=people_index.NS_WIKI_USERNAME,
                value="User:Magnus Manske",
                normalized_value="user:magnus manske",
                identifier_kind=people_index.IDENTIFIER_HANDLE,
                source="toolhub_author_metadata",
            )
        )
        trusted = people_index.ensure_person(
            s,
            display_name="Trusted Toolforge maintainer",
            toolforge_username="trusted-maintainer",
            source="toolforge_toolsadmin",
        )

        summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)

        assert summary["identityQualitiesRefreshed"] == 1
        assert person.identity_quality == "handle"
        assert person.id not in people_index.public_identity_ids(s, {person.id})
        assert trusted.id in people_index.public_identity_ids(s, {trusted.id})


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


def test_identity_only_resolution_does_not_rebuild_canonical_tool_evidence():
    _configure()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="untouched-tool",
                record={"name": "untouched-tool", "author": [{"name": "Ada"}]},
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver(),
            rebuild_tools=False,
        )

        assert summary["toolsRebuilt"] == 0
        assert s.query(ToolRelationshipEvidence).count() == 0


def test_identity_batch_limit_counts_resolvable_accounts_not_unmatched_labels():
    _configure()
    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "unknown-tool",
            "source",
            [{"display_name": "A name without account", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        people_index.replace_source_evidence(
            s,
            "mix-n-match",
            "source",
            [{"display_name": "Magnus Manske", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver("mix-n-match"),
            candidate_label_limit=1,
        )

        assert summary["identityMappingsApplied"] == 1


def test_identity_batch_prioritizes_the_largest_unresolved_account_group():
    _configure()
    with db.session_scope() as s:
        small = Person(canonical_key="display:alpha", display_name="Alpha", identity_quality="display_name")
        large = [
            Person(canonical_key=f"display:zulu-{index}", display_name="Zulu", identity_quality="display_name")
            for index in range(3)
        ]
        s.add_all(
            [
                small,
                *large,
                ToolhubAccountProjection(
                    toolhub_user_id="1",
                    username="Alpha",
                    normalized_username="alpha",
                ),
                ToolhubAccountProjection(
                    toolhub_user_id="2",
                    username="Zulu",
                    normalized_username="zulu",
                ),
            ]
        )
        s.flush()

        groups = people_reconcile._candidate_account_groups(s, [small, *large])

        assert [(account.username, len(sources)) for account, sources in groups] == [("Zulu", 3), ("Alpha", 1)]


def test_apply_links_only_same_tool_sul_membership_and_keeps_other_attribution_candidate():
    _configure()
    with db.session_scope() as s:
        for tool_name in ("mix-n-match", "other-tool"):
            people_index.replace_source_evidence(
                s,
                tool_name,
                "toolhub_author_metadata",
                [{"display_name": "Magnus Manske", "relationship_type": sync.PERSON_REL_AUTHOR}],
            )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver("mix-n-match"),
        )

        assert summary["identityCandidatesCreated"] == 2
        assert summary["identityMappingsApplied"] == 1
        mappings = s.query(PersonReconciliationMapping).order_by(PersonReconciliationMapping.confidence.desc()).all()
        assert [row.confidence for row in mappings] == [95, 70]
        assert [row.decision for row in mappings] == ["auto_link", "candidate"]
        assert mappings[0].evidence["matchedToolforgeMemberships"] == ["mix-n-match"]
        target_ids = {row.target_person_id for row in mappings}
        assert len(target_ids) == 1
        target_identifiers = {
            (row.namespace, row.value)
            for row in s.query(PersonIdentifier).filter(PersonIdentifier.person_id.in_(target_ids))
        }
        assert target_identifiers == {
            ("toolforge_uid_number", "3067"),
            ("toolforge_username", "magnus"),
            ("toolhub_user_id", "152"),
            ("toolhub_username", "Magnus Manske"),
            ("wikimedia_global_user_id", "160"),
            ("wiki_username", "Magnus Manske"),
        }
        assert ("toolforge_username", "Magnus Manske") not in target_identifiers
        assert s.query(ToolRelationshipEvidence).filter_by(tool_name="mix-n-match").one().person_id in target_ids

        rerun = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver("mix-n-match"),
        )
        assert rerun["identityCandidatesCreated"] == 0
        assert s.query(PersonReconciliationMapping).count() == 2


def test_centralauth_confirmed_wiki_handles_link_authorship_without_toolforge_membership():
    _configure()
    with db.session_scope() as s:
        for tool_name, wiki_username in (
            ("hotcat", "Magnus Manske"),
            ("glamorgan", "User:Magnus_Manske"),
        ):
            people_index.replace_source_evidence(
                s,
                tool_name,
                "toolhub_author_metadata",
                [
                    {
                        "display_name": "Magnus Manske",
                        "wiki_username": wiki_username,
                        "relationship_type": sync.PERSON_REL_AUTHOR,
                    }
                ],
            )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver(),
        )

        assert summary["identityMappingsApplied"] == 2
        mappings = s.query(PersonReconciliationMapping).order_by(PersonReconciliationMapping.id).all()
        assert {mapping.decision for mapping in mappings} == {"auto_link"}
        assert {mapping.reason for mapping in mappings} == {"same_verified_structured_handle"}
        assert {mapping.confidence for mapping in mappings} == {90}
        assert {mapping.evidence["resolutionVersion"] for mapping in mappings} == {
            people_reconcile.IDENTITY_RESOLUTION_VERSION
        }
        assert {mapping.evidence["verifiedWikimediaHandle"] for mapping in mappings} == {
            "Magnus Manske",
            "User:Magnus_Manske",
        }
        relationships = s.query(ToolPersonRelationship).order_by(ToolPersonRelationship.tool_name).all()
        assert {row.relationship_type for row in relationships} == {sync.PERSON_REL_AUTHOR}
        assert len({row.person_id for row in relationships}) == 1


def test_unconfirmed_wiki_handle_remains_a_review_candidate():
    _configure()
    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "unrelated-tool",
            "toolhub_author_metadata",
            [
                {
                    "display_name": "Magnus Manske",
                    "wiki_username": "Someone else",
                    "relationship_type": sync.PERSON_REL_AUTHOR,
                }
            ],
        )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver(),
        )

        assert summary["identityMappingsApplied"] == 0
        mapping = s.query(PersonReconciliationMapping).one()
        assert mapping.decision == "candidate"
        assert mapping.reason == "exact_toolhub_username_candidate"
        assert mapping.evidence["verifiedWikimediaHandle"] == ""


def test_recent_legacy_candidate_is_rechecked_when_it_has_a_wiki_handle():
    _configure()
    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "hotcat",
            "toolhub_author_metadata",
            [
                {
                    "display_name": "Magnus Manske",
                    "wiki_username": "Magnus Manske",
                    "relationship_type": sync.PERSON_REL_AUTHOR,
                }
            ],
        )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )
        unavailable = PublicIdentityResolver(
            wikimedia=WikimediaIdentityProvider(fetcher=lambda _id: (503, {})),
            toolforge=ToolforgeIdentityProvider(lookup=lambda _username: []),
        )
        first = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=unavailable,
        )
        assert first["identityMappingsApplied"] == 0
        mapping = s.query(PersonReconciliationMapping).one()
        mapping.evidence = dict(mapping.evidence or {}) | {"resolutionVersion": 2}
        s.flush()

        second = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver(),
        )

        assert second["identityMappingsApplied"] == 1
        assert mapping.decision == "auto_link"
        assert mapping.evidence["resolutionVersion"] == people_reconcile.IDENTITY_RESOLUTION_VERSION


def test_toolsadmin_tool_account_name_corroborates_a_differently_named_toolhub_record():
    _configure()
    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "mm_baglama",
            "toolforge_toolsadmin",
            [
                {
                    "display_name": "Magnus Manske",
                    "relationship_type": sync.PERSON_REL_MAINTAINER,
                    "method": sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    "verification_status": sync.AUTHOR_CLAIM_VERIFIED,
                    "confidence": 95,
                    "evidence_payload": {"toolforgeToolName": "glamtools", "profileUsername": ""},
                }
            ],
        )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver("glamtools"),
        )

        assert summary["identityMappingsApplied"] == 1
        mapping = s.query(PersonReconciliationMapping).one()
        assert mapping.decision == "auto_link"
        assert mapping.evidence["toolNames"] == ["mm_baglama"]
        assert mapping.evidence["toolforgeToolNames"] == ["glamtools"]
        assert mapping.evidence["matchedToolforgeMemberships"] == ["glamtools"]
        relationship = s.query(ToolPersonRelationship).filter_by(tool_name="mm_baglama").one()
        target = s.query(PersonIdentifier).filter_by(namespace="toolforge_uid_number", value="3067").one()
        assert relationship.person_id == target.person_id


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
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver(),
        )

        assert summary["identityCandidatesCreated"] == 0
        assert summary["stableIdentityConflicts"] == 1
        assert s.query(PersonReconciliationMapping).count() == 0
        conflict = s.query(PersonReconciliationConflict).filter_by(conflict_type="conflicting_stable_identifiers").one()
        assert conflict.details["toolhubPersonId"] == toolhub_person.public_id
        assert conflict.details["wikimediaPersonId"] == wikimedia_person.public_id
        assert toolhub_person.id != wikimedia_person.id


def test_conflicting_toolforge_uid_number_never_overwrites_a_stable_person():
    _configure()
    with db.session_scope() as s:
        account_person = people_index.ensure_official_account_person(
            s,
            toolhub_user_id="152",
            username="Magnus Manske",
            wikimedia_global_user_id="160",
        )
        toolforge_person = people_index.ensure_person(
            s,
            display_name="Different developer",
            toolforge_uid_number="3067",
            toolforge_username="different",
        )
        people_index.replace_source_evidence(
            s,
            "mix-n-match",
            "source",
            [{"display_name": "Magnus Manske", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver("mix-n-match"),
        )

        assert summary["identityMappingsApplied"] == 0
        assert summary["stableIdentityConflicts"] == 1
        assert s.query(PersonReconciliationMapping).count() == 0
        conflict = s.query(PersonReconciliationConflict).filter_by(conflict_type="conflicting_stable_identifiers").one()
        assert conflict.details["toolhubPersonId"] == account_person.public_id
        assert conflict.details["toolforgePersonId"] == toolforge_person.public_id
