# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic people and evidence reconciliation."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import (  # noqa: E402
    db,
    identity_graph,
    maintainer_index,
    people_index,
    people_policy,
    people_reconcile,
    sync,
    wikimedia_user_reconciliation,
)
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    Person,
    PersonAccountBinding,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationQueue,
    PersonReconciliationRun,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    ToolforgeAccountProjection,
    ToolhubAccountProjection,
    User,
    utcnow,
)
from backend.public_identity import (  # noqa: E402
    PublicIdentityResolver,
    ToolforgeIdentityProvider,
    WikimediaIdentity,
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


def test_toolhub_display_values_are_not_projected_as_toolforge_handles():
    observations = maintainer_index._toolhub_observations(  # noqa: SLF001 - adapter contract regression
        {
            "author": [
                {
                    "name": "Magnus Manske",
                    "developer_username": "Magnus Manske",
                    "wiki_username": "User:Magnus_Manske",
                }
            ]
        }
    )

    assert observations[0]["toolforge_username"] == ""
    assert observations[0]["wiki_username"] == "User:Magnus_Manske"


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
                source="legacy_untrusted_metadata",
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


def test_applied_mapping_hides_only_non_stable_source_identity():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        target = people_index.ensure_person(s, display_name="Canonical", toolhub_user_id="42")
        source = people_index.ensure_person(
            s,
            display_name="Alias",
            toolforge_username="alias",
            source="toolforge_toolsadmin",
        )
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=source.id,
            target_person_id=target.id,
            decision=people_reconcile.MAPPING_CANDIDATE,
        )
        s.add(mapping)
        s.flush()

        assert people_index.public_identity_ids(s, {source.id}) == {source.id}
        mapping.decision = people_reconcile.MAPPING_APPROVED
        s.flush()
        assert people_index.public_identity_ids(s, {source.id}) == set()

        s.add(
            PersonIdentifier(
                person_id=source.id,
                namespace=people_index.NS_TOOLFORGE_UID_NUMBER,
                value="99",
                normalized_value="99",
                identifier_kind=people_index.IDENTIFIER_STABLE,
                source="wikimedia_toolforge_bridge",
            )
        )
        s.flush()
        assert people_index.public_identity_ids(s, {source.id}) == {source.id}


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


def test_incremental_queue_reenqueue_resets_retry_state_without_losing_attempt_history():
    _configure()
    with db.session_scope() as s:
        s.add(
            PersonReconciliationQueue(
                tool_name="retry-tool",
                reason="failed_run",
                attempts=3,
                next_attempt_at=utcnow(),
                last_error="temporary failure",
            )
        )

    assert people_reconcile.enqueue_tool_names(["retry-tool"], reason="canonical_fetch") == 1

    with db.session_scope() as s:
        row = s.get(PersonReconciliationQueue, "retry-tool")
        assert row is not None
        assert row.reason == "canonical_fetch"
        assert row.attempts == 3
        assert row.next_attempt_at is None
        assert row.last_error is None


def test_confirmed_catalog_retirement_withdraws_evidence_and_public_relationships():
    _configure()
    with db.session_scope() as s:
        person = people_index.ensure_person(
            s,
            display_name="Retired Maintainer",
            toolforge_username="retired-maintainer",
        )
        people_index.replace_source_evidence(
            s,
            "retired-tool",
            maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN,
            [
                {
                    "display_name": "Retired Maintainer",
                    "toolforge_username": "retired-maintainer",
                    "relationship_type": sync.PERSON_REL_MAINTAINER,
                }
            ],
        )
        public_id = person.public_id

    people_reconcile.enqueue_tool_names(["retired-tool"], reason="canonical_retired")
    summary = people_reconcile.process_queue(limit=1)

    assert summary == {"claimed": 1, "processed": 1, "failed": 0}
    with db.session_scope() as s:
        assert s.query(ToolPersonRelationship).filter_by(tool_name="retired-tool").count() == 0
        evidence = s.query(ToolRelationshipEvidence).filter_by(tool_name="retired-tool").one()
        assert evidence.withdrawn_at is not None
        assert people_index.person_detail(s, public_id)["toolCount"] == 0


def test_retirement_drain_leaves_ordinary_reconciliation_work_queued():
    _configure()
    people_reconcile.enqueue_tool_names(["changed-tool"], reason="canonical_fetch")
    people_reconcile.enqueue_tool_names(["retired-tool"], reason="canonical_retired")

    summary = people_reconcile.drain_queue(reason="canonical_retired")

    assert summary == {"claimed": 1, "processed": 1, "failed": 0, "batches": 1}
    with db.session_scope() as s:
        assert s.get(PersonReconciliationQueue, "retired-tool") is None
        assert s.get(PersonReconciliationQueue, "changed-tool") is not None


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


def test_identity_only_registry_resolution_applies_wikimedia_user_space_rule():
    _configure()
    with db.session_scope() as s:
        now = utcnow()
        s.add(
            CanonicalToolCache(
                tool_name="enwiki-enterprisey-tool",
                record={
                    "name": "enwiki-enterprisey-tool",
                    "url": "https://en.wikipedia.org/wiki/User:Enterprisey/tool.js",
                    "author": [{"name": "Enterprisey"}],
                },
                expires_at=now,
                stale_until=now,
            )
        )
        s.add(
            ToolforgeAccountProjection(
                uid_number="9001",
                uid="enterprisey",
                normalized_uid="enterprisey",
                developer_username="Enterprisey",
                normalized_developer_username="enterprisey",
            )
        )
        people_index.replace_source_evidence(
            s,
            "enwiki-enterprisey-tool",
            "toolhub_author_metadata",
            [{"display_name": "Enterprisey", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        resolved_registry = (
            [("enterprisey", WikimediaIdentity(global_user_id="500", username="Enterprisey"))],
            "enterprisey",
        )

        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            registry_label_limit=1,
            rebuild_tools=False,
            sync_accounts=False,
            refresh_sources=False,
            resolved_identity_candidates=[],
            resolved_registry_candidates=resolved_registry,
        )

        assert summary["registryPeopleCreated"] == 1
        assert summary["wikimediaUserSpaceReconciliation"]["verifiedTools"] == 1
        relationship = s.query(ToolPersonRelationship).filter_by(relationship_type="author").one()
        assert relationship.verification_status == "verified"


def test_a_caller_that_published_user_space_evidence_is_not_made_to_publish_it_twice(monkeypatch):
    """`user_space_result` is how the entrypoint keeps that phase's locks short.

    Run inline, `synchronize` writes `person_identifiers` and those row locks
    are held until the whole pass commits -- twenty minutes for
    `--identities-only`. The entrypoint runs it in a transaction of its own and
    hands the counts down; this pins that handing them down actually skips the
    inline pass rather than silently running it a second time under the lock it
    was moved out of.
    """
    _configure()
    calls = []
    monkeypatch.setattr(
        wikimedia_user_reconciliation,
        "synchronize",
        lambda _s: calls.append(1) or wikimedia_user_reconciliation.empty_stats(),
    )
    published = wikimedia_user_reconciliation.empty_stats()
    published["verifiedTools"] = 4
    published["authorEvidence"] = 9

    with db.session_scope() as s:
        summary = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            rebuild_tools=False,
            sync_accounts=False,
            refresh_sources=False,
            user_space_result=published,
        )

    assert calls == []
    # Reported, not discarded: the counts are the record of what the pass did,
    # and the phase that produced them no longer appears in this summary's own
    # transaction to speak for itself.
    assert summary["wikimediaUserSpaceReconciliation"] == published


def test_the_default_still_publishes_user_space_evidence_inline(monkeypatch):
    """Short-transaction callers -- projection publication, and these tests --
    pay nothing for the lock window and should not have to plumb the phase."""
    _configure()
    calls = []
    monkeypatch.setattr(
        wikimedia_user_reconciliation,
        "synchronize",
        lambda _s: calls.append(1) or wikimedia_user_reconciliation.empty_stats(),
    )

    with db.session_scope() as s:
        people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            rebuild_tools=False,
            sync_accounts=False,
            refresh_sources=False,
        )

    assert calls == [1]


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

        assert summary["identityMappingsApplied"] == 0
        assert s.query(PersonReconciliationMapping).count() == 0
        assert (
            people_index.search_unresolved_attributions(s, people_index.UnresolvedAttributionQuery(page_size=10))[
                "count"
            ]
            == 2
        )


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

        assert summary["identityCandidatesCreated"] == 0
        assert summary["identityMappingsApplied"] == 0
        assert s.query(PersonReconciliationMapping).count() == 0
        attribution = people_index.search_unresolved_attributions(
            s, people_index.UnresolvedAttributionQuery(query="Magnus Manske", page_size=10)
        )["results"][0]
        assert attribution["toolCount"] == 2
        assert attribution["attributionCount"] == 2

        rerun = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver("mix-n-match"),
        )
        assert rerun["identityCandidatesCreated"] == 0
        assert s.query(PersonReconciliationMapping).count() == 0


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
        assert people_index.public_identity_ids(s, {mapping.source_person_id for mapping in mappings}) == set()
        relationships = s.query(ToolPersonRelationship).order_by(ToolPersonRelationship.tool_name).all()
        assert {row.relationship_type for row in relationships} == {sync.PERSON_REL_AUTHOR}
        assert len({row.person_id for row in relationships}) == 1


def test_auto_link_repairs_structured_evidence_recreated_on_its_source():
    _configure()
    with db.session_scope() as s:
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="152",
                username="Magnus Manske",
                normalized_username="magnus manske",
                wikimedia_global_user_id="160",
            )
        )
        observation = {
            "display_name": "Magnus Manske",
            "wiki_username": "User:Magnus_Manske",
            "relationship_type": sync.PERSON_REL_AUTHOR,
        }
        people_index.replace_source_evidence(
            s,
            "hotcat",
            "toolhub_author_metadata",
            [observation],
        )
        first = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver(),
        )
        mapping = s.query(PersonReconciliationMapping).one()
        source = s.get(Person, mapping.source_person_id)
        target = s.get(Person, mapping.target_person_id)
        assert first["identityMappingsApplied"] == 1

        people_index.replace_source_evidence(
            s,
            "hotcat",
            "toolhub_author_metadata",
            [observation],
        )
        assert s.query(ToolPersonRelationship).filter_by(person_id=source.id).count() == 1
        assert [person.id for person in people_reconcile._candidate_source_people(s)] == [source.id]  # noqa: SLF001

        second = people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            identity_resolver=_identity_resolver(),
            rebuild_tools=False,
        )

        assert second["identityCandidatesCreated"] == 0
        assert second["identityMappingsApplied"] == 1
        assert s.query(ToolPersonRelationship).filter_by(person_id=source.id).count() == 0
        assert s.query(ToolPersonRelationship).filter_by(person_id=target.id).count() == 1


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

        assert summary["identityMappingsApplied"] == 0
        assert s.query(PersonReconciliationMapping).count() == 0
        attribution = people_index.search_unresolved_attributions(
            s, people_index.UnresolvedAttributionQuery(query="Magnus Manske", page_size=10)
        )["results"][0]
        assert attribution["toolCount"] == 1
        assert attribution["bestConfidence"] == 95


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
        assert summary["stableIdentityConflicts"] == 0
        assert s.query(PersonReconciliationMapping).count() == 0
        assert summary["accountBindings"]["toolhubBindings"] == 0
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
        assert summary["stableIdentityConflicts"] == 0
        assert s.query(PersonReconciliationMapping).count() == 0
        assert account_person.id != toolforge_person.id


def test_enqueue_ignores_blank_tool_names():
    _configure()
    assert people_reconcile.enqueue_tool_names(["", "   "], reason="data_ingestion") == 0
    with db.session_scope() as s:
        assert s.query(PersonReconciliationQueue).count() == 0


def test_enqueue_refreshes_an_existing_queue_row_and_clears_retry_state():
    _configure()
    assert people_reconcile.enqueue_tool_names(["stuck-tool"], reason="data_ingestion") == 1
    with db.session_scope() as s:
        row = s.get(PersonReconciliationQueue, "stuck-tool")
        row.next_attempt_at = utcnow()
        row.last_error = "previous failure"
        row.attempts = 3

    assert people_reconcile.enqueue_tool_names(["stuck-tool"], reason="canonical_fetch") == 1
    with db.session_scope() as s:
        row = s.get(PersonReconciliationQueue, "stuck-tool")
        assert row.reason == "canonical_fetch"
        assert row.next_attempt_at is None
        assert row.last_error is None


def test_enqueue_supports_mysql_and_portable_database_dialects(monkeypatch):
    class MysqlStatement:
        inserted = type("Inserted", (), {"reason": "reason", "enqueued_at": "time"})()

        def values(self, rows):
            self.rows = rows
            return self

        @staticmethod
        def on_duplicate_key_update(**_values):
            return "mysql-upsert"

    mysql_statement = MysqlStatement()
    monkeypatch.setattr(people_reconcile, "mysql_insert", lambda _model: mysql_statement)

    class MysqlSession:
        @staticmethod
        def get_bind():
            return type("Bind", (), {"dialect": type("Dialect", (), {"name": "mysql"})()})()

        @staticmethod
        def execute(statement):
            assert statement == "mysql-upsert"

    assert people_reconcile.enqueue_tool_names_in_session(MysqlSession(), ["alpha"]) == 1

    existing = PersonReconciliationQueue(tool_name="existing", reason="old", enqueued_at=utcnow())

    class PortableSession:
        added = []

        @staticmethod
        def get_bind():
            return type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

        @staticmethod
        def get(_model, name):
            return existing if name == "existing" else None

        @classmethod
        def add(cls, row):
            cls.added.append(row)

    assert people_reconcile.enqueue_tool_names_in_session(
        PortableSession(), ["new", "existing"], reason=""
    ) == 2
    assert PortableSession.added[0].tool_name == "new"
    assert existing.reason == "data_ingestion"
    assert existing.next_attempt_at is None
    assert existing.last_error is None


def test_remote_registry_batch_throttles_after_the_first_lookup(monkeypatch):
    _configure()
    monkeypatch.setattr(people_reconcile, "_candidate_source_people", lambda _session: [])
    monkeypatch.setattr(people_reconcile, "_candidate_account_groups", lambda *_args: [])
    monkeypatch.setattr(people_reconcile, "_registry_label_batch", lambda *_args, **_kwargs: (["Ada", "Grace"], "g"))
    sleeps = []
    provider = WikimediaIdentityProvider(fetcher=lambda _username: (200, {"query": {"globaluserinfo": {}}}))

    _identities, (registry, cursor) = people_reconcile.resolve_remote_batches(
        registry_provider=provider,
        registry_label_limit=2,
        sleep=sleeps.append,
    )

    assert [label for label, _identity in registry] == ["Ada", "Grace"]
    assert cursor == "g"
    assert sleeps == [people_reconcile.REGISTRY_MIN_INTERVAL_SECONDS]


def test_move_mapping_evidence_returns_empty_set_without_both_person_ids():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id, source_person_id=None, target_person_id=None, decision=people_reconcile.MAPPING_CANDIDATE
        )
        s.add(mapping)
        s.flush()

        assert people_reconcile._move_mapping_evidence(s, mapping) == set()  # noqa: SLF001


def test_apply_mapping_merges_evidence_into_a_higher_confidence_duplicate():
    _configure()
    with db.session_scope() as s:
        target = people_index.ensure_person(s, display_name="Target Stable", toolhub_user_id="900")
        source = people_index.ensure_person(
            s, display_name="Source Alias", toolforge_username="source-alias", source="toolforge_toolsadmin"
        )
        s.add(
            ToolRelationshipEvidence(
                tool_name="dup-tool",
                person_id=target.id,
                relationship_type=sync.PERSON_REL_AUTHOR,
                source="toolhub_author_metadata",
                method="author_display_name",
                evidence_key="k1",
                confidence=50,
                verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
            )
        )
        s.add(
            ToolRelationshipEvidence(
                tool_name="dup-tool",
                person_id=source.id,
                relationship_type=sync.PERSON_REL_AUTHOR,
                source="toolhub_author_metadata",
                method="author_display_name",
                evidence_key="k1",
                confidence=90,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                evidence_url="https://example.org/proof",
            )
        )
        s.flush()
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=source.id,
            target_person_id=target.id,
            decision=people_reconcile.MAPPING_APPROVED,
        )
        s.add(mapping)
        s.flush()

        affected = people_reconcile.apply_mapping(s, mapping)

        assert affected == 1
        remaining = s.query(ToolRelationshipEvidence).filter_by(tool_name="dup-tool").all()
        assert len(remaining) == 1
        merged = remaining[0]
        assert merged.person_id == target.id
        assert merged.confidence == 90
        assert merged.verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert merged.evidence_url == "https://example.org/proof"


def test_apply_mapping_noop_for_non_applied_decision():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id, source_person_id=1, target_person_id=2, decision=people_reconcile.MAPPING_CANDIDATE
        )
        s.add(mapping)
        s.flush()

        assert people_reconcile.apply_mapping(s, mapping) == 0


def test_apply_mapping_requires_source_and_target_ids():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=None,
            target_person_id=None,
            decision=people_reconcile.MAPPING_APPROVED,
        )
        s.add(mapping)
        s.flush()

        with pytest.raises(people_reconcile.PersonReconciliationError, match="must name source and target"):
            people_reconcile.apply_mapping(s, mapping)


def test_apply_mapping_rejects_matching_source_and_target():
    _configure()
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Solo")
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=person.id,
            target_person_id=person.id,
            decision=people_reconcile.MAPPING_APPROVED,
        )
        s.add(mapping)
        s.flush()

        with pytest.raises(people_reconcile.PersonReconciliationError, match="must differ"):
            people_reconcile.apply_mapping(s, mapping)


def test_apply_mapping_requires_target_with_stable_identity():
    _configure()
    with db.session_scope() as s:
        source = people_index.ensure_person(s, display_name="Src")
        target = people_index.ensure_person(s, display_name="Tgt Unstable")
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=source.id,
            target_person_id=target.id,
            decision=people_reconcile.MAPPING_APPROVED,
        )
        s.add(mapping)
        s.flush()

        with pytest.raises(people_reconcile.PersonReconciliationError, match="stable identity evidence"):
            people_reconcile.apply_mapping(s, mapping)


def test_apply_mapping_refuses_when_source_gained_stable_identity():
    _configure()
    with db.session_scope() as s:
        target = people_index.ensure_person(s, display_name="Tgt Stable", toolhub_user_id="777")
        source = people_index.ensure_person(s, display_name="Src Now Stable", wikimedia_global_user_id="778")
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=source.id,
            target_person_id=target.id,
            decision=people_reconcile.MAPPING_APPROVED,
        )
        s.add(mapping)
        s.flush()

        with pytest.raises(people_reconcile.PersonReconciliationError, match="conflict review"):
            people_reconcile.apply_mapping(s, mapping)


def test_process_queue_skips_a_row_removed_before_its_turn(monkeypatch):
    _configure()
    people_reconcile.enqueue_tool_names(["a", "b"])
    original = people_reconcile._reconcile_tool  # noqa: SLF001

    def fake(s, name, *, retired=False):
        if name == "a":
            s.query(PersonReconciliationQueue).filter_by(tool_name="b").delete()
            return
        original(s, name, retired=retired)

    monkeypatch.setattr(people_reconcile, "_reconcile_tool", fake)

    summary = people_reconcile.process_queue(limit=2)

    assert summary == {"claimed": 2, "processed": 1, "failed": 0}
    with db.session_scope() as s:
        assert s.get(PersonReconciliationQueue, "a") is None
        assert s.get(PersonReconciliationQueue, "b") is None


def test_process_queue_records_failure_and_schedules_a_retry(monkeypatch):
    _configure()
    people_reconcile.enqueue_tool_names(["boom"])

    def raiser(s, name, *, retired=False):
        raise RuntimeError("boom failure")

    monkeypatch.setattr(people_reconcile, "_reconcile_tool", raiser)

    summary = people_reconcile.process_queue(limit=1)

    assert summary == {"claimed": 1, "processed": 0, "failed": 1}
    with db.session_scope() as s:
        row = s.get(PersonReconciliationQueue, "boom")
        assert row is not None
        assert row.attempts == 1
        assert row.next_attempt_at is not None
        assert row.last_error == "boom failure"


def test_drain_queue_stops_after_max_batches_without_an_empty_claim():
    _configure()
    people_reconcile.enqueue_tool_names(["only-tool"])

    summary = people_reconcile.drain_queue(max_batches=1)

    assert summary == {"claimed": 1, "processed": 1, "failed": 0, "batches": 1}
    with db.session_scope() as s:
        assert s.get(PersonReconciliationQueue, "only-tool") is None


def test_recent_candidate_without_structured_evidence_is_not_yet_due():
    _configure()
    with db.session_scope() as s:
        person = Person(
            canonical_key="display:no-handle-yet", display_name="No Handle Yet", identity_quality="display_name"
        )
        s.add(person)
        s.flush()
        s.add(
            ToolPersonRelationship(
                tool_name="quiet-tool", person_id=person.id, relationship_type=sync.PERSON_REL_AUTHOR
            )
        )
        s.flush()
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=person.id,
            decision=people_reconcile.MAPPING_CANDIDATE,
            evidence={},
        )
        s.add(mapping)
        s.flush()

        due_ids = [p.id for p in people_reconcile._candidate_source_people(s)]  # noqa: SLF001

        assert person.id not in due_ids


def test_source_evidence_for_person_collects_toolforge_tool_names():
    _configure()
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Direct Evidence Person")
        s.add(
            ToolPersonRelationship(
                tool_name="direct-tool", person_id=person.id, relationship_type=sync.PERSON_REL_MAINTAINER
            )
        )
        s.add(
            ToolRelationshipEvidence(
                tool_name="direct-tool",
                person_id=person.id,
                relationship_type=sync.PERSON_REL_MAINTAINER,
                source=maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN,
                method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                evidence_key="k1",
                evidence_payload={"toolforgeToolName": "glamtools"},
            )
        )
        s.add(
            ToolRelationshipEvidence(
                tool_name="direct-tool",
                person_id=person.id,
                relationship_type=sync.PERSON_REL_MAINTAINER,
                source=maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN,
                method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                evidence_key="k2",
                evidence_payload={"profileUsername": ""},
            )
        )
        s.flush()

        tool_names, toolforge_names, roles = people_reconcile._source_evidence_for_person(s, person.id)  # noqa: SLF001

        assert tool_names == ["direct-tool"]
        assert toolforge_names == ["glamtools"]
        assert roles == [sync.PERSON_REL_MAINTAINER]


def test_membership_aliases_skips_blank_names():
    aliases = people_reconcile._membership_aliases(["", "   ", "Toolforge-Foo"])  # noqa: SLF001

    assert aliases == {"toolforge-foo", "foo"}


def test_stable_identifier_owner_ignores_blank_values():
    _configure()
    with db.session_scope() as s:
        assert people_reconcile._stable_identifier_owner(s, people_index.NS_TOOLHUB_USER_ID, "") is None  # noqa: SLF001


def test_verified_wikimedia_handle_ignores_blank_canonical_username():
    _configure()
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Someone")
        assert people_reconcile._verified_wikimedia_handle(s, person.id, "") == ""  # noqa: SLF001


def test_record_stable_identity_conflict_creates_and_reuses_pending_row():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        toolhub_person = people_index.ensure_person(s, display_name="Toolhub Owner", toolhub_user_id="1")
        wikimedia_person = people_index.ensure_person(s, display_name="Wikimedia Owner", wikimedia_global_user_id="2")
        account = ToolhubAccountProjection(
            toolhub_user_id="1",
            username="Someone",
            normalized_username="someone",
            wikimedia_global_user_id="2",
        )
        s.add(account)
        s.flush()

        assert people_reconcile._record_stable_identity_conflict(s, run.id, account) is True  # noqa: SLF001
        conflict = s.query(PersonReconciliationConflict).one()
        assert conflict.details["toolhubPersonId"] == toolhub_person.public_id
        assert conflict.details["wikimediaPersonId"] == wikimedia_person.public_id
        assert "toolforgePersonId" not in conflict.details

        assert people_reconcile._record_stable_identity_conflict(s, run.id, account) is True  # noqa: SLF001
        assert s.query(PersonReconciliationConflict).count() == 1


def test_record_stable_identity_conflict_covers_the_toolforge_owner():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        wikimedia_person = people_index.ensure_person(
            s, display_name="Wikimedia Owner Two", wikimedia_global_user_id="20"
        )
        toolforge_person = people_index.ensure_person(
            s, display_name="Toolforge Owner", toolforge_uid_number="30", toolforge_username="toolforge-owner"
        )
        account = ToolhubAccountProjection(
            toolhub_user_id="99",
            username="Nobody Local",
            normalized_username="nobody local",
            wikimedia_global_user_id="20",
        )
        s.add(account)
        s.flush()

        created = people_reconcile._record_stable_identity_conflict(  # noqa: SLF001
            s, run.id, account, toolforge_uid_number="30"
        )

        assert created is True
        conflict = s.query(PersonReconciliationConflict).one()
        assert "toolhubPersonId" not in conflict.details
        assert conflict.details["wikimediaPersonId"] == wikimedia_person.public_id
        assert conflict.details["toolforgePersonId"] == toolforge_person.public_id


def test_record_stable_identity_conflict_without_a_wikimedia_owner():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        toolhub_person = people_index.ensure_person(s, display_name="Toolhub Only Owner", toolhub_user_id="40")
        toolforge_person = people_index.ensure_person(
            s, display_name="Toolforge Only Owner", toolforge_uid_number="41", toolforge_username="toolforge-only"
        )
        account = ToolhubAccountProjection(
            toolhub_user_id="40", username="No Wikimedia", normalized_username="no wikimedia"
        )
        s.add(account)
        s.flush()

        created = people_reconcile._record_stable_identity_conflict(  # noqa: SLF001
            s, run.id, account, toolforge_uid_number="41"
        )

        assert created is True
        conflict = s.query(PersonReconciliationConflict).one()
        assert conflict.details["toolhubPersonId"] == toolhub_person.public_id
        assert "wikimediaPersonId" not in conflict.details
        assert conflict.details["toolforgePersonId"] == toolforge_person.public_id


def test_process_queue_records_failure_even_when_the_row_vanishes_mid_flight(monkeypatch):
    _configure()
    people_reconcile.enqueue_tool_names(["vanish"])

    def raiser(s, name, *, retired=False):
        s.query(PersonReconciliationQueue).filter_by(tool_name=name).delete()
        s.commit()
        raise RuntimeError("vanished mid-flight")

    monkeypatch.setattr(people_reconcile, "_reconcile_tool", raiser)

    summary = people_reconcile.process_queue(limit=1)

    assert summary == {"claimed": 1, "processed": 0, "failed": 1}
    with db.session_scope() as s:
        assert s.get(PersonReconciliationQueue, "vanish") is None


def test_record_account_binding_conflicts_updates_an_existing_pending_row():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        person = people_index.ensure_person(s, display_name="Conflicted Account Holder")
        binding = PersonAccountBinding(
            provider="wikimedia",
            external_id="900",
            person_id=person.id,
            status=identity_graph.STATUS_CONFLICT,
            proof_method="toolforge_ldap_wikimedia_global_id",
            evidence={"note": "first"},
        )
        s.add(binding)
        s.flush()

        assert people_reconcile._record_account_binding_conflicts(s, run.id) == 1  # noqa: SLF001
        conflict = s.query(PersonReconciliationConflict).one()
        assert conflict.value == "wikimedia:900"

        binding.evidence = {"note": "second"}
        s.flush()

        assert people_reconcile._record_account_binding_conflicts(s, run.id) == 1  # noqa: SLF001
        assert s.query(PersonReconciliationConflict).count() == 1
        assert conflict.details["evidence"]["note"] == "second"


def test_candidate_account_groups_skips_labels_without_an_exact_account():
    _configure()
    with db.session_scope() as s:
        matched = Person(canonical_key="display:known", display_name="Known", identity_quality="display_name")
        unmatched = Person(
            canonical_key="display:mystery", display_name="Mystery Person", identity_quality="display_name"
        )
        s.add_all(
            [
                matched,
                unmatched,
                ToolhubAccountProjection(toolhub_user_id="5", username="Known", normalized_username="known"),
            ]
        )
        s.flush()

        groups = people_reconcile._candidate_account_groups(s, [matched, unmatched])  # noqa: SLF001

        assert [account.username for account, _sources in groups] == ["Known"]


def test_registry_corroborated_requires_tool_names_and_verified_evidence():
    _configure()
    with db.session_scope() as s:
        target = people_index.ensure_person(s, display_name="Target Person")

        assert (
            people_reconcile._registry_corroborated(s, target_person_id=target.id, tool_names=[]) is False  # noqa: SLF001
        )
        assert (
            people_reconcile._registry_corroborated(  # noqa: SLF001
                s, target_person_id=target.id, tool_names=["some-tool"]
            )
            is False
        )

        s.add(
            ToolRelationshipEvidence(
                tool_name="some-tool",
                person_id=target.id,
                relationship_type=sync.PERSON_REL_AUTHOR,
                source="toolhub_author_metadata",
                method="author_display_name",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            )
        )
        s.flush()

        assert (
            people_reconcile._registry_corroborated(  # noqa: SLF001
                s, target_person_id=target.id, tool_names=["some-tool"]
            )
            is True
        )


def test_upsert_mapping_reuses_an_existing_mapping_row():
    _configure()
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        source = people_index.ensure_person(s, display_name="Reused Source")
        target1 = people_index.ensure_person(s, display_name="Target One", toolhub_user_id="10")
        target2 = people_index.ensure_person(s, display_name="Target Two", toolhub_user_id="11")
        decision = people_policy.decide_identity_link(registry_handle=True)

        mapping, created = people_reconcile._upsert_mapping(  # noqa: SLF001
            s, run_id=run.id, source=source, target=target1, decision=decision, evidence={"round": 1}
        )
        assert created is True
        assert s.query(PersonReconciliationMapping).count() == 1

        mapping_again, created_again = people_reconcile._upsert_mapping(  # noqa: SLF001
            s, run_id=run.id, source=source, target=target2, decision=decision, evidence={"round": 2}
        )
        assert created_again is False
        assert mapping_again.id == mapping.id
        assert mapping_again.target_person_id == target2.id
        assert s.query(PersonReconciliationMapping).count() == 1


def test_discover_identity_candidates_records_conflict_and_skips_the_source():
    _configure()
    with db.session_scope() as s:
        toolhub_person = people_index.ensure_person(s, display_name="Toolhub Stable", toolhub_user_id="700")
        wikimedia_person = people_index.ensure_person(
            s, display_name="Wikimedia Stable", wikimedia_global_user_id="701"
        )
        source = Person(
            canonical_key="display:conflicted", display_name="Conflicted Label", identity_quality="display_name"
        )
        s.add(source)
        s.flush()
        s.add(
            ToolPersonRelationship(
                tool_name="conflict-tool", person_id=source.id, relationship_type=sync.PERSON_REL_AUTHOR
            )
        )
        s.add(
            ToolRelationshipEvidence(
                tool_name="conflict-tool",
                person_id=source.id,
                relationship_type=sync.PERSON_REL_AUTHOR,
                source="toolhub_author_metadata",
            )
        )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="700",
                username="Conflicted Label",
                normalized_username="conflicted label",
                wikimedia_global_user_id="701",
            )
        )
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        resolver = PublicIdentityResolver(
            wikimedia=WikimediaIdentityProvider(
                fetcher=lambda _id: (200, {"query": {"globaluserinfo": {"id": "701", "name": "Conflicted Label"}}})
            ),
            toolforge=ToolforgeIdentityProvider(
                lookup=lambda _u: [
                    {
                        "uid": ["cl"],
                        "uidNumber": ["9999"],
                        "wikimediaGlobalAccountId": ["701"],
                        "wikimediaGlobalAccountName": ["Conflicted Label"],
                        "memberOf": [],
                    }
                ]
            ),
        )

        result = people_reconcile.discover_identity_candidates(s, run_id=run.id, identity_resolver=resolver)

        assert result["conflicts"] == 1
        assert result["created"] == 0
        assert s.query(PersonReconciliationMapping).count() == 0
        assert toolhub_person.id != wikimedia_person.id


def test_discover_identity_candidates_counts_conflict_when_account_person_is_refused(monkeypatch):
    _configure()
    with db.session_scope() as s:
        source = Person(
            canonical_key="display:refused", display_name="Refused Label", identity_quality="display_name"
        )
        s.add(source)
        s.flush()
        s.add(
            ToolPersonRelationship(
                tool_name="refused-tool", person_id=source.id, relationship_type=sync.PERSON_REL_AUTHOR
            )
        )
        s.add(
            ToolRelationshipEvidence(
                tool_name="refused-tool",
                person_id=source.id,
                relationship_type=sync.PERSON_REL_AUTHOR,
                source="toolhub_author_metadata",
            )
        )
        s.add(
            ToolhubAccountProjection(
                toolhub_user_id="800", username="Refused Label", normalized_username="refused label"
            )
        )
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        monkeypatch.setattr(people_index, "ensure_official_account_person", lambda *_a, **_k: None)

        result = people_reconcile.discover_identity_candidates(
            s, run_id=run.id, identity_resolver=_identity_resolver()
        )

        assert result["conflicts"] == 1
        assert result["created"] == 0


def test_run_rejects_an_unknown_mode():
    _configure()
    with db.session_scope() as s:
        with pytest.raises(people_reconcile.PersonReconciliationError, match="bogus-mode"):
            people_reconcile.run(s, mode="bogus-mode")


def test_identities_only_run_resolves_remote_batch_before_people_writes(monkeypatch):
    _configure()
    events = []
    monkeypatch.setattr(
        people_reconcile,
        "_resolve_identity_candidate_batch",
        lambda *_args, **_kwargs: events.append("remote") or [],
    )
    monkeypatch.setattr(
        people_index,
        "refresh_identity_qualities",
        lambda _session: events.append("people-write") or 0,
    )

    with db.session_scope() as s:
        people_reconcile.run(
            s,
            mode=people_reconcile.MODE_APPLY,
            discover_candidates=True,
            registry_label_limit=0,
            rebuild_tools=False,
            sync_accounts=False,
            refresh_sources=False,
        )

    assert events == ["remote", "people-write"]


def test_reconvergence_runs_after_every_evidence_phase_of_the_same_pass(monkeypatch):
    # Ordering is load-bearing: it decides observations against evidence, so an
    # edge this pass just created has to be visible to it. Running it earlier
    # would defer that edge's effect by a whole pass.
    _configure()
    events = []
    monkeypatch.setattr(
        people_reconcile.identity_graph,
        "synchronize",
        lambda _session: events.append("accounts") or {"membershipRelationships": 0},
    )
    monkeypatch.setattr(
        people_reconcile.source_attestations,
        "refresh_incremental",
        lambda *_args, **_kwargs: events.append("sources")
        or {"sources": 0, "tools": 0, "authorEvidence": 0, "maintainerEvidence": 0},
    )
    monkeypatch.setattr(
        people_reconcile,
        "reconverge_attributions",
        lambda *_args, **_kwargs: events.append("reconverge") or {"examined": 3, "promoted": 2, "tools": 1},
    )

    with db.session_scope() as session:
        result = people_reconcile.run(
            session,
            mode=people_reconcile.MODE_APPLY,
            rebuild_tools=False,
            sync_accounts=True,
            refresh_sources=True,
        )

    assert events == ["accounts", "sources", "reconverge"]
    assert result["attributionReconvergence"] == {"examined": 3, "promoted": 2, "tools": 1}


def test_reconvergence_is_skipped_when_its_batch_is_disabled(monkeypatch):
    _configure()
    monkeypatch.setattr(
        people_reconcile,
        "reconverge_attributions",
        lambda *_args, **_kwargs: pytest.fail("a zero batch must not read the backlog"),
    )

    with db.session_scope() as session:
        result = people_reconcile.run(
            session,
            mode=people_reconcile.MODE_APPLY,
            rebuild_tools=False,
            sync_accounts=False,
            refresh_sources=False,
            reconverge_limit=0,
        )

    assert result["attributionReconvergence"] == {"examined": 0, "promoted": 0, "tools": 0}


def test_run_skips_source_refresh_when_full_audit_owns_writer_lock(monkeypatch):
    _configure()

    class BusyLock:
        def __enter__(self):
            return False

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(people_reconcile.db, "advisory_lock", lambda *_args, **_kwargs: BusyLock())
    monkeypatch.setattr(
        people_reconcile.source_attestations,
        "refresh_incremental",
        lambda *_args, **_kwargs: pytest.fail("busy source writer must not be entered"),
    )

    with db.session_scope() as session:
        result = people_reconcile.run(
            session,
            mode=people_reconcile.MODE_APPLY,
            rebuild_tools=False,
            sync_accounts=False,
            refresh_sources=True,
        )

    assert result["sourceAttestations"]["locked"] is True


def test_run_marks_the_row_failed_and_reraises_on_an_unexpected_error(monkeypatch):
    _configure()
    with db.session_scope() as s:

        def boom(_s):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(people_reconcile, "build_plan", boom)

        with pytest.raises(RuntimeError, match="kaboom"):
            people_reconcile.run(s, mode=people_reconcile.MODE_DRY_RUN)

        run_row = s.query(PersonReconciliationRun).one()
        assert run_row.status == people_reconcile.RUN_FAILED
        assert run_row.error == "kaboom"
        assert run_row.completed_at is not None


def test_an_unchanged_conflict_is_not_rewritten_on_every_run():
    """A standing conflict must not cost a write each pass.

    Every run rewrote `run_id` and `last_seen_at` on conflicts whose details
    were byte-for-byte identical, so the same rows were updated hourly for
    nothing. Two of those runs overlapping deadlocked on
    `person_reconciliation_conflicts` -- MySQL 1213 on the timestamp UPDATE --
    and the job stayed down until someone noticed. Nothing downstream reads
    `last_seen_at` more finely than the throttle, so the write is skipped while
    the conflict is unchanged and still refreshed once the interval passes.
    """
    _configure()
    with db.session_scope() as s:
        first = PersonReconciliationRun(mode="apply", status="completed")
        second = PersonReconciliationRun(mode="apply", status="completed")
        s.add_all([first, second])
        s.flush()
        people_index.ensure_person(s, display_name="Toolhub Owner", toolhub_user_id="1")
        people_index.ensure_person(s, display_name="Wikimedia Owner", wikimedia_global_user_id="2")
        account = ToolhubAccountProjection(
            toolhub_user_id="1",
            username="Someone",
            normalized_username="someone",
            wikimedia_global_user_id="2",
        )
        s.add(account)
        s.flush()

        people_reconcile._record_stable_identity_conflict(s, first.id, account)  # noqa: SLF001
        s.flush()
        conflict = s.query(PersonReconciliationConflict).one()
        seen_at = conflict.last_seen_at
        conflict.run_id = first.id

        # Same details, same hour: the row is left exactly as it stands.
        people_reconcile._record_stable_identity_conflict(s, second.id, account)  # noqa: SLF001
        s.flush()
        assert conflict.run_id == first.id
        assert conflict.last_seen_at == seen_at

        # Once the throttle has elapsed the row is refreshed again, so a
        # conflict that has genuinely gone quiet is still distinguishable.
        conflict.last_seen_at = seen_at - people_reconcile.CONFLICT_REFRESH_AFTER
        people_reconcile._record_stable_identity_conflict(s, second.id, account)  # noqa: SLF001
        s.flush()
        assert conflict.run_id == second.id
        assert conflict.last_seen_at > seen_at - people_reconcile.CONFLICT_REFRESH_AFTER


def _standing_conflict(s):
    """A pending stable-identity conflict plus a later run that re-observes it."""
    first = PersonReconciliationRun(mode="apply", status="completed")
    second = PersonReconciliationRun(mode="apply", status="completed")
    s.add_all([first, second])
    s.flush()
    people_index.ensure_person(s, display_name="Toolhub Owner", toolhub_user_id="1")
    people_index.ensure_person(s, display_name="Wikimedia Owner", wikimedia_global_user_id="2")
    account = ToolhubAccountProjection(
        toolhub_user_id="1",
        username="Someone",
        normalized_username="someone",
        wikimedia_global_user_id="2",
    )
    s.add(account)
    s.flush()
    people_reconcile._record_stable_identity_conflict(s, first.id, account)  # noqa: SLF001
    s.flush()
    return s.query(PersonReconciliationConflict).one(), account, first, second


def test_a_stale_conflict_hands_its_timestamp_to_the_caller_instead_of_writing_it():
    """The refresh is cosmetic; the transaction it used to be written in was not.

    Writing `last_seen_at` inline takes a row lock for the rest of the pass --
    twenty minutes of one, for `--identities-only` -- on a table
    `source_attestations` also writes. On 2026-08-28 that collision waited out
    the fifty-second `innodb_lock_wait_timeout` and destroyed a run three
    minutes in, over a two-column UPDATE nothing reads. Given a sink, the pass
    collects the id and touches no row at all.
    """
    _configure()
    deferred: list[int] = []
    with db.session_scope() as s:
        conflict, account, first, second = _standing_conflict(s)
        stale = conflict.last_seen_at - people_reconcile.CONFLICT_REFRESH_AFTER
        conflict.last_seen_at = stale
        conflict.run_id = first.id
        s.flush()
        people_reconcile._record_stable_identity_conflict(  # noqa: SLF001
            s, second.id, account, deferred_conflict_refreshes=deferred
        )
        s.flush()
        assert deferred == [conflict.id]
        assert conflict.run_id == first.id
        assert conflict.last_seen_at == stale


def test_a_changed_conflict_is_still_written_by_the_pass_that_decided_it():
    """Only the timestamp defers. What the queue shows is real data and stays inline."""
    _configure()
    deferred: list[int] = []
    with db.session_scope() as s:
        conflict, account, _first, second = _standing_conflict(s)
        conflict.details = dict(conflict.details) | {"reason": "something else entirely"}
        s.flush()
        people_reconcile._record_stable_identity_conflict(  # noqa: SLF001
            s, second.id, account, deferred_conflict_refreshes=deferred
        )
        s.flush()
        assert deferred == []
        assert conflict.run_id == second.id
        assert conflict.details["reason"].startswith("Cross-system stable identifiers")


def test_deferred_refreshes_are_applied_once_the_pass_has_committed():
    """Deferring is only half the fix: the timestamps still have to land."""
    _configure()
    deferred: list[int] = []
    with db.session_scope() as s:
        conflict, account, first, second = _standing_conflict(s)
        stale = conflict.last_seen_at - people_reconcile.CONFLICT_REFRESH_AFTER
        conflict.last_seen_at = stale
        conflict.run_id = first.id
        s.flush()
        people_reconcile._record_stable_identity_conflict(  # noqa: SLF001
            s, second.id, account, deferred_conflict_refreshes=deferred
        )
        second_id = second.id

    # Duplicates are what two passes over the same standing conflict produce;
    # they must cost one UPDATE, not one per sighting.
    applied = people_reconcile.refresh_conflicts_seen([*deferred, *deferred], run_id=second_id)
    assert applied == {"requested": 1, "refreshed": 1}
    with db.session_scope() as s:
        conflict = s.query(PersonReconciliationConflict).one()
        assert conflict.run_id == second_id
        assert conflict.last_seen_at > stale


def test_nothing_deferred_costs_no_transaction_at_all():
    """The common hour: every conflict unchanged and inside the throttle."""
    _configure()

    def explode() -> None:
        raise AssertionError("refresh opened a transaction for an empty list")

    assert people_reconcile.refresh_conflicts_seen([], run_id=1) == {"requested": 0, "refreshed": 0}
    # Proved by the counts above rather than by patching, but assert the seam too:
    # an empty list must not reach the retry helper.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "run_with_lock_retry", lambda *_a, **_k: explode())
        assert people_reconcile.refresh_conflicts_seen([], run_id=1)["refreshed"] == 0


def test_a_lost_lock_on_the_refresh_does_not_fail_a_run_that_already_committed():
    """The reason the write was deferred cannot be allowed to kill it anyway.

    By the time this runs the pass has committed, so raising here would throw
    away a completed run over a timestamp -- exactly the loss the deferral was
    built to stop. The shortfall shows in the counts instead.
    """
    _configure()
    locked = OperationalError("UPDATE person_reconciliation_conflicts", {}, Exception(1205, "Lock wait timeout"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "run_with_lock_retry", lambda *_a, **_k: (_ for _ in ()).throw(locked))
        assert people_reconcile.refresh_conflicts_seen([7], run_id=3) == {"requested": 1, "refreshed": 0}


def test_a_refresh_that_can_never_succeed_is_not_swallowed():
    """A lock is forgiven; a broken statement is not, or the fix hides its own bugs."""
    _configure()
    broken = OperationalError("UPDATE person_reconciliation_conflicts", {}, Exception(1054, "Unknown column"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "run_with_lock_retry", lambda *_a, **_k: (_ for _ in ()).throw(broken))
        with pytest.raises(OperationalError):
            people_reconcile.refresh_conflicts_seen([7], run_id=3)
