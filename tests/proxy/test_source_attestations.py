# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for generic source-attestation reconciliation."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, source_attestations, toolinfo_authors, toolinfo_sources  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCacheMeta,
    CanonicalToolCache,
    Person,
    PersonAccountBinding,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationRun,
    ToolAuthorClaim,
    ToolRelationshipEvidence,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolinfoAuthorBinding,
    ToolinfoSource,
    ToolinfoSourceAttestation,
    ToolinfoSourceGeneration,
    ToolinfoSourceItem,
    UnresolvedAttributionEvidence,
    User,
    utcnow,
)


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _canonical(session, name):
    now = utcnow()
    session.add(
        CanonicalToolCache(
            tool_name=name,
            record={"name": name},
            source_url=f"https://toolhub.example/{name}",
            expires_at=now + timedelta(days=1),
            stale_until=now + timedelta(days=2),
        )
    )


def _stable_person(session, name, uid_number, uid, global_id):
    return people_index.ensure_person(
        session,
        display_name=name,
        wikimedia_global_user_id=global_id,
        toolforge_uid_number=uid_number,
        toolforge_username=uid,
        wiki_username=name,
        source="test_stable_identity",
    )


def _toolforge_member(session, person, *, project, uid_number, uid):
    session.add(
        ToolforgeAccountProjection(
            uid_number=uid_number,
            uid=uid,
            normalized_uid=uid.casefold(),
        )
    )
    session.add(ToolforgeMembershipProjection(uid_number=uid_number, tool_name=project))
    session.add(
        PersonAccountBinding(
            provider="toolforge",
            external_id=uid_number,
            person_id=person.id,
            status="verified",
            proof_method="test_stable_binding",
            confidence=100,
        )
    )


def _source(session, url, payloads):
    source = ToolinfoSource(url=url, source_kind="self_hosted_toolinfo", status="valid", valid=True)
    session.add(source)
    session.flush()
    for payload in payloads:
        session.add(
            ToolinfoSourceItem(
                source_id=source.id,
                source_url=url,
                tool_name=payload["name"],
                title=payload.get("title", payload["name"]),
                tool_url=payload["url"],
                payload=payload,
            )
        )
    session.flush()
    return source


def test_author_parser_emits_independent_structured_and_legacy_authors():
    structured = toolinfo_authors.author_assertions(
        {
            "author": [
                {"name": "Ada", "wiki_username": "Ada Wiki", "developer_username": "ada"},
                {"name": "Grace", "developer_username": "grace"},
            ]
        }
    )
    legacy = toolinfo_authors.author_assertions({"author": "Magnus Manske, JoanJoc"})

    assert [(row.display_name, row.position) for row in structured] == [("Ada", 0), ("Grace", 100)]
    assert [(row.display_name, row.legacy_delimited) for row in legacy] == [
        ("Magnus Manske", True),
        ("JoanJoc", True),
    ]
    assert toolinfo_authors.author_names({"author": "Magnus Manske, JoanJoc"}) == [
        "Magnus Manske",
        "JoanJoc",
    ]
    assert toolinfo_authors.author_names({"author": "Lovelace, Ada"}) == ["Lovelace, Ada"]


def test_single_source_controller_propagates_only_matching_author_tokens():
    with db.session_scope() as session:
        magnus = _stable_person(session, "Magnus Manske", "3067", "magnus", "160")
        _toolforge_member(session, magnus, project="magnustools", uid_number="3067", uid="magnus")
        _canonical(session, "tool-one")
        _canonical(session, "tool-two")
        source = _source(
            session,
            "https://magnustools.toolforge.org/toolinfo.json",
            [
                {
                    "name": "tool-one",
                    "title": "One",
                    "description": "One",
                    "url": "https://one.example",
                    "author": "Magnus Manske",
                },
                {
                    "name": "tool-two",
                    "title": "Two",
                    "description": "Two",
                    "url": "https://two.example",
                    "author": "Magnus Manske, JoanJoc",
                },
            ],
        )
        result = source_attestations.refresh_source_ids(session, [source.id])

        run = session.execute(select(PersonReconciliationRun)).scalar_one()
        assert run.mode == source_attestations.RECONCILIATION_RUN_MODE
        assert len(run.mode) <= PersonReconciliationRun.mode.type.length

        attestation = session.get(ToolinfoSourceAttestation, source.id)
        bindings = {
            row.normalized_label: row
            for row in session.execute(select(ToolinfoAuthorBinding)).scalars()
        }
        magnus_edges = list(
            session.execute(
                select(ToolRelationshipEvidence).where(
                    ToolRelationshipEvidence.source == source_attestations.SOURCE_AUTHOR_ATTESTATION,
                    ToolRelationshipEvidence.person_id == magnus.id,
                )
            ).scalars()
        )
        unresolved = list(session.execute(select(UnresolvedAttributionEvidence)).scalars())

        assert result["verified"] == 1
        assert result["unresolved"] == 1
        assert attestation.classification == source_attestations.CLASS_SINGLE
        assert attestation.controller_person_id == magnus.id
        assert bindings["magnus manske"].status == source_attestations.STATUS_VERIFIED
        assert bindings["joanjoc"].status == source_attestations.STATUS_UNRESOLVED
        assert {row.tool_name for row in magnus_edges} == {"tool-one", "tool-two"}
        assert [(row.tool_name, row.observed_label) for row in unresolved] == [("tool-two", "JoanJoc")]
        assert unresolved[0].evidence_payload["legacyDelimited"] is True


def test_group_controlled_source_does_not_choose_an_arbitrary_member():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "10", "ada", "100")
        grace = _stable_person(session, "Grace", "11", "grace", "101")
        _toolforge_member(session, ada, project="shared", uid_number="10", uid="ada")
        _toolforge_member(session, grace, project="shared", uid_number="11", uid="grace")
        _canonical(session, "shared-tool")
        source = _source(
            session,
            "https://shared.toolforge.org/toolinfo.json",
            [
                {
                    "name": "shared-tool",
                    "title": "Shared",
                    "description": "Shared",
                    "url": "https://shared.example",
                    "author": "Ada",
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])

        attestation = session.get(ToolinfoSourceAttestation, source.id)
        binding = session.execute(select(ToolinfoAuthorBinding)).scalar_one()
        assert attestation.classification == source_attestations.CLASS_GROUP
        assert attestation.controller_person_id is None
        assert binding.status == source_attestations.STATUS_UNRESOLVED
        assert binding.person_id is None


def test_structured_handle_resolves_identity_without_overstating_verification():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada Lovelace", "10", "ada", "100")
        _canonical(session, "structured-tool")
        source = _source(
            session,
            "https://metadata.example/toolinfo.json",
            [
                {
                    "name": "structured-tool",
                    "title": "Structured",
                    "description": "Structured",
                    "url": "https://structured.example",
                    "author": [{"name": "Ada", "wiki_username": "Ada Lovelace"}],
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])

        binding = session.execute(select(ToolinfoAuthorBinding)).scalar_one()
        edge = session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.source == source_attestations.SOURCE_AUTHOR_ATTESTATION
            )
        ).scalar_one()
        assert binding.person_id == ada.id
        assert binding.status == source_attestations.STATUS_RESOLVED
        assert edge.person_id == ada.id
        assert edge.verification_status == "unverified"


def test_one_verified_tool_anchor_propagates_source_scoped_authorship():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada Lovelace", "10", "ada", "100")
        _canonical(session, "anchored-tool")
        _canonical(session, "second-tool")
        source = _source(
            session,
            "https://metadata.example/toolinfo.json",
            [
                {
                    "name": name,
                    "title": name,
                    "description": name,
                    "url": f"https://{name}.example",
                    "author": "Ada Lovelace",
                }
                for name in ("anchored-tool", "second-tool")
            ],
        )
        people_index.replace_source_evidence(
            session,
            "anchored-tool",
            "independent_verification",
            [
                {
                    "display_name": "Ada Lovelace",
                    "wikimedia_global_user_id": "100",
                    "relationship_type": "maintainer",
                    "method": "independent_stable_proof",
                    "evidence_key": "100",
                    "verification_status": "verified",
                    "confidence": 100,
                }
            ],
        )

        source_attestations.refresh_source_ids(session, [source.id])
        binding = session.execute(select(ToolinfoAuthorBinding)).scalar_one()
        propagated = list(
            session.execute(
                select(ToolRelationshipEvidence).where(
                    ToolRelationshipEvidence.source == source_attestations.SOURCE_AUTHOR_ATTESTATION,
                    ToolRelationshipEvidence.person_id == ada.id,
                )
            ).scalars()
        )

        assert binding.method == source_attestations.METHOD_VERIFIED_ANCHOR
        assert binding.status == source_attestations.STATUS_VERIFIED
        assert {row.tool_name for row in propagated} == {"anchored-tool", "second-tool"}


def test_target_toolforge_membership_is_verified_per_target_project():
    with db.session_scope() as session:
        operator = _stable_person(session, "Operator", "20", "operator", "200")
        _toolforge_member(session, operator, project="target-project", uid_number="20", uid="operator")
        _canonical(session, "target-tool")
        source = _source(
            session,
            "https://metadata.example/toolinfo.json",
            [
                {
                    "name": "target-tool",
                    "title": "Target",
                    "description": "Target",
                    "url": "https://target-project.toolforge.org",
                    "author": "Someone Else",
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])
        edge = session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.source == source_attestations.SOURCE_TARGET_MEMBERSHIP
            )
        ).scalar_one()

        assert edge.person_id == operator.id
        assert edge.relationship_type == "maintainer"
        assert edge.verification_status == "verified"
        assert edge.evidence_payload["toolforgeProject"] == "target-project"


def test_failed_fetch_retains_last_good_generation_and_relationship_evidence():
    with db.session_scope() as session:
        source = _source(
            session,
            "https://source.example/toolinfo.json",
            [
                {
                    "name": "kept-tool",
                    "title": "Kept",
                    "description": "Kept",
                    "url": "https://kept.example",
                    "author": "Ada",
                }
            ],
        )
        source_id = source.id
    toolinfo_sources._store_source_items(
        source_id,
        [
            {
                "tool_name": "kept-tool",
                "title": "Kept",
                "tool_url": "https://kept.example",
                "payload": {
                    "name": "kept-tool",
                    "title": "Kept",
                    "description": "Kept",
                    "url": "https://kept.example",
                    "author": "Ada",
                },
            }
        ],
    )
    toolinfo_sources._mark_source_error(source_id, "temporary timeout")

    with db.session_scope() as session:
        source = session.get(ToolinfoSource, source_id)
        assert source.status == "error"
        assert source.valid is True
        assert session.query(ToolinfoSourceItem).count() == 1
        assert session.query(ToolinfoSourceGeneration).count() == 1


def test_unchanged_feed_generation_skips_item_rewrite_and_attestation_work():
    item = {
        "tool_name": "stable-tool",
        "title": "Stable",
        "tool_url": "https://stable.example",
        "payload": {
            "name": "stable-tool",
            "title": "Stable",
            "description": "Stable",
            "url": "https://stable.example",
        },
    }
    with db.session_scope() as session:
        source = _source(session, "https://stable.example/toolinfo.json", [item["payload"]])
        source_id = source.id
    _count, first_changed = toolinfo_sources._store_source_items(source_id, [item])
    with db.session_scope() as session:
        source_attestations.refresh_full(session)
        item_id = session.execute(select(ToolinfoSourceItem.id)).scalar_one()

    count, second_changed = toolinfo_sources._store_source_items(source_id, [item])
    with db.session_scope() as session:
        incremental = source_attestations.refresh_incremental(session)
        assert session.execute(select(ToolinfoSourceItem.id)).scalar_one() == item_id
        assert session.query(ToolinfoSourceGeneration).count() == 2

    assert first_changed == ["stable-tool"]
    assert count == 1
    assert second_changed == []
    assert incremental["sources"] == 0
    assert incremental["tools"] == 0


def test_complete_empty_generation_withdraws_items_bindings_and_attributions():
    with db.session_scope() as session:
        _canonical(session, "removed-tool")
        source = _source(
            session,
            "https://source.example/toolinfo.json",
            [
                {
                    "name": "removed-tool",
                    "title": "Removed",
                    "description": "Removed",
                    "url": "https://removed.example",
                    "author": "Unresolved Author",
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])
        source_id = source.id

    count, changed = toolinfo_sources._store_source_items(source_id, [])
    with db.session_scope() as session:
        source_attestations.refresh_source_ids(session, [source_id], affected_tool_names=changed)
        source = session.get(ToolinfoSource, source_id)
        binding = session.execute(select(ToolinfoAuthorBinding)).scalar_one()
        unresolved = session.execute(select(UnresolvedAttributionEvidence)).scalar_one()
        assert count == 0
        assert source.valid is False
        assert session.query(ToolinfoSourceItem).count() == 0
        assert binding.withdrawn_at is not None
        assert unresolved.withdrawn_at is not None


def test_conflicting_source_proofs_enter_operator_queue_and_fail_closed():
    with db.session_scope() as session:
        source = _source(
            session,
            "https://conflict.example/toolinfo.json",
            [
                {
                    "name": "conflict-tool",
                    "title": "Conflict",
                    "description": "Conflict",
                    "url": "https://conflict.example",
                    "author": "Same Label",
                }
            ],
        )
        _canonical(session, "conflict-tool")
        first = _stable_person(session, "First", "30", "first", "300")
        second = _stable_person(session, "Second", "31", "second", "301")
        from backend.models import ToolAuthorClaim, User

        for index, person in enumerate((first, second), start=1):
            user = User(wm_sub=str(index), username=f"user-{index}", person_id=person.id)
            session.add(user)
            session.flush()
            session.add(
                ToolAuthorClaim(
                    tool_name="conflict-tool",
                    author_name="Same Label",
                    toolhub_username=user.username,
                    user_id=user.id,
                    verification_status="verified",
                    verification_method="toolinfo_url_control",
                    evidence_url=source.url,
                    expires_at=utcnow() + timedelta(days=1),
                )
            )
        source_attestations.refresh_source_ids(session, [source.id])

        attestation = session.get(ToolinfoSourceAttestation, source.id)
        binding = session.execute(select(ToolinfoAuthorBinding)).scalar_one()
        conflicts = list(session.execute(select(PersonReconciliationConflict)).scalars())
        assert attestation.classification == source_attestations.CLASS_CONFLICT
        assert binding.person_id is None
        assert conflicts[0].conflict_type == "toolinfo_source_identity"
        assert conflicts[0].status == "pending"


def test_wiki_user_from_source_url_prefers_a_matching_wiki_path_candidate():
    # The query-string "title" candidate is tried first but has no "User:"
    # prefix, so it is skipped; the loop falls through to the "/wiki/" path
    # segment, which does carry the prefix and is trimmed to its first
    # path component.
    url = "https://en.wikipedia.org/wiki/User:Ada_Lovelace/talk?title=Not_A_User_Page"
    assert source_attestations.wiki_user_from_source_url(url) == "Ada_Lovelace"

    # Neither candidate has a "User:" prefix: the function falls off the end
    # and returns "".
    assert source_attestations.wiki_user_from_source_url("https://example.org/wiki/Some_Article") == ""


def test_normalized_identity_strips_user_namespace_prefix():
    assert source_attestations._normalized_identity("User:Ada Lovelace") == "ada lovelace"
    assert source_attestations._normalized_identity("Ada Lovelace") == "ada lovelace"


def test_verified_person_for_handle_rejects_empty_ambiguous_and_non_public_matches():
    with db.session_scope() as session:
        # An empty (whitespace-only) handle never resolves.
        assert (
            source_attestations._verified_person_for_handle(session, people_index.NS_WIKI_USERNAME, "   ") is None
        )

        # Two people whose handles collide only under this module's looser
        # normalization (not the stored normalized_value used for the
        # uniqueness constraint) are ambiguous, not a match.
        first = _stable_person(session, "First Person", "91", "first91", "910")
        second = _stable_person(session, "Second Person", "92", "second92", "920")
        session.add(
            PersonIdentifier(
                person_id=first.id,
                namespace=people_index.NS_WIKI_USERNAME,
                value="User:Ada",
                normalized_value="user:ada",
                identifier_kind="handle",
                source="test_ambiguous",
            )
        )
        session.add(
            PersonIdentifier(
                person_id=second.id,
                namespace=people_index.NS_WIKI_USERNAME,
                value="Ada",
                normalized_value="ada",
                identifier_kind="handle",
                source="test_ambiguous",
            )
        )
        session.flush()
        assert (
            source_attestations._verified_person_for_handle(session, people_index.NS_WIKI_USERNAME, "Ada") is None
        )

        # A single match whose person is not a public identity (a bare
        # untrusted handle, no stable id, no profile) does not resolve.
        private_person = Person(canonical_key="display:private handle person", display_name="Private Handle Person")
        session.add(private_person)
        session.flush()
        session.add(
            PersonIdentifier(
                person_id=private_person.id,
                namespace=people_index.NS_WIKI_USERNAME,
                value="Private Handle",
                normalized_value="private handle",
                identifier_kind="handle",
                source="untrusted_source",
            )
        )
        session.flush()
        assert (
            source_attestations._verified_person_for_handle(
                session, people_index.NS_WIKI_USERNAME, "Private Handle"
            )
            is None
        )


def test_wikimedia_user_page_verifies_single_person_control():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada Lovelace", "40", "adawiki", "400")
        _canonical(session, "wiki-tool")
        source = _source(
            session,
            "https://en.wikipedia.org/wiki/User:Ada_Lovelace",
            [
                {
                    "name": "wiki-tool",
                    "title": "Wiki",
                    "description": "Wiki",
                    "url": "https://wiki-tool.example",
                    "author": "Someone Unrelated",
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])

        attestation = session.get(ToolinfoSourceAttestation, source.id)
        assert attestation.classification == source_attestations.CLASS_SINGLE
        assert attestation.status == source_attestations.STATUS_VERIFIED
        assert attestation.controller_person_id == ada.id
        assert attestation.method == "wikimedia_user_page_control"
        assert attestation.confidence == 95
        assert attestation.evidence["wikiUsername"] == "Ada_Lovelace"


def test_single_verified_source_control_claim_verifies_the_controller():
    with db.session_scope() as session:
        _canonical(session, "solo-tool")
        source = _source(
            session,
            "https://solo-claim.example/toolinfo.json",
            [
                {
                    "name": "solo-tool",
                    "title": "Solo",
                    "description": "Solo",
                    "url": "https://solo.example",
                    "author": "Solo Author",
                }
            ],
        )
        owner = _stable_person(session, "Owner", "50", "owner", "500")
        user = User(wm_sub="50", username="owner-user", person_id=owner.id)
        session.add(user)
        session.flush()
        session.add(
            ToolAuthorClaim(
                tool_name="solo-tool",
                author_name="Solo Author",
                toolhub_username=user.username,
                user_id=user.id,
                verification_status="verified",
                verification_method="toolinfo_url_control",
                evidence_url=source.url,
                expires_at=utcnow() + timedelta(days=1),
            )
        )
        source_attestations.refresh_source_ids(session, [source.id])

        attestation = session.get(ToolinfoSourceAttestation, source.id)
        assert attestation.classification == source_attestations.CLASS_SINGLE
        assert attestation.status == source_attestations.STATUS_VERIFIED
        assert attestation.controller_person_id == owner.id
        assert attestation.method == "challenged_source_control"
        assert attestation.confidence == 100


def test_single_toolforge_member_without_a_verified_binding_stays_unknown():
    with db.session_scope() as session:
        _canonical(session, "loose-tool")
        source = _source(
            session,
            "https://loose.toolforge.org/toolinfo.json",
            [
                {
                    "name": "loose-tool",
                    "title": "Loose",
                    "description": "Loose",
                    "url": "https://loose.example",
                    "author": "Nobody Verified",
                }
            ],
        )
        session.add(ToolforgeAccountProjection(uid_number="60", uid="looseuser", normalized_uid="looseuser"))
        session.add(ToolforgeMembershipProjection(uid_number="60", tool_name="loose"))
        source_attestations.refresh_source_ids(session, [source.id])

        attestation = session.get(ToolinfoSourceAttestation, source.id)
        assert attestation.classification == source_attestations.CLASS_UNKNOWN
        assert attestation.status == source_attestations.STATUS_UNRESOLVED
        assert attestation.controller_person_id is None
        assert attestation.evidence["toolforgeProject"] == "loose"
        assert attestation.evidence["activeMemberCount"] == 1
        assert attestation.evidence["toolforgeUidNumber"] == "60"


def test_official_registry_service_account_is_classified_as_service():
    with db.session_scope() as session:
        source = ToolinfoSource(
            url="https://registry.example/toolinfo.json",
            source_kind="self_hosted_toolinfo",
            status="valid",
            valid=True,
            created_by_username="Toolhub",
        )
        session.add(source)
        session.flush()
        session.add(
            ToolinfoSourceItem(
                source_id=source.id,
                source_url=source.url,
                tool_name="service-tool",
                title="Service",
                tool_url="https://service.example",
                payload={
                    "name": "service-tool",
                    "title": "Service",
                    "description": "Service",
                    "url": "https://service.example",
                    "author": "Someone",
                },
            )
        )
        session.flush()
        source_attestations.refresh_source_ids(session, [source.id])

        attestation = session.get(ToolinfoSourceAttestation, source.id)
        assert attestation.classification == source_attestations.CLASS_SERVICE
        assert attestation.method == "official_registry_service_account"
        assert attestation.status == source_attestations.STATUS_UNRESOLVED
        assert attestation.controller_person_id is None


def test_conflicting_source_control_conflict_record_is_updated_on_rerun():
    with db.session_scope() as session:
        _canonical(session, "rerun-conflict-tool")
        source = _source(
            session,
            "https://rerun-conflict.example/toolinfo.json",
            [
                {
                    "name": "rerun-conflict-tool",
                    "title": "Conflict",
                    "description": "Conflict",
                    "url": "https://rerun-conflict.example",
                    "author": "Same Label",
                }
            ],
        )
        first = _stable_person(session, "First", "32", "first32", "320")
        second = _stable_person(session, "Second", "33", "second33", "330")
        for index, person in enumerate((first, second), start=1):
            user = User(wm_sub=f"rerun-{index}", username=f"rerun-user-{index}", person_id=person.id)
            session.add(user)
            session.flush()
            session.add(
                ToolAuthorClaim(
                    tool_name="rerun-conflict-tool",
                    author_name="Same Label",
                    toolhub_username=user.username,
                    user_id=user.id,
                    verification_status="verified",
                    verification_method="toolinfo_url_control",
                    evidence_url=source.url,
                    expires_at=utcnow() + timedelta(days=1),
                )
            )
        source_id = source.id

    with db.session_scope() as session:
        source_attestations.refresh_source_ids(session, [source_id])
        first_conflict = session.execute(select(PersonReconciliationConflict)).scalar_one()
        first_conflict_id = first_conflict.id
        first_run_id = first_conflict.run_id
        first_binding = session.execute(select(ToolinfoAuthorBinding)).scalar_one()
        first_binding_id = first_binding.id

    with db.session_scope() as session:
        # Re-running against the still-open conflict updates the existing
        # row (and reuses the existing author binding row) instead of
        # duplicating either.
        source_attestations.refresh_source_ids(session, [source_id])
        conflicts = list(session.execute(select(PersonReconciliationConflict)).scalars())
        bindings = list(session.execute(select(ToolinfoAuthorBinding)).scalars())
        assert len(conflicts) == 1
        assert conflicts[0].id == first_conflict_id
        assert conflicts[0].run_id != first_run_id
        assert len(bindings) == 1
        assert bindings[0].id == first_binding_id


def test_conflicting_structured_identity_evidence_is_recorded_as_a_binding_conflict():
    with db.session_scope() as session:
        alice = _stable_person(session, "Alice", "70", "alice-dev", "700")
        bob = _stable_person(session, "bob-wiki", "71", "bobdev", "701")
        _canonical(session, "mismatched-tool")
        source = _source(
            session,
            "https://metadata.example/mismatched.json",
            [
                {
                    "name": "mismatched-tool",
                    "title": "Mismatched",
                    "description": "Mismatched",
                    "url": "https://mismatched.example",
                    "author": [
                        {
                            "name": "Ambiguous",
                            "developer_username": "alice-dev",
                            "wiki_username": "bob-wiki",
                        }
                    ],
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])

        binding = session.execute(select(ToolinfoAuthorBinding)).scalar_one()
        conflict = session.execute(
            select(PersonReconciliationConflict).where(
                PersonReconciliationConflict.conflict_type == "toolinfo_source_identity"
            )
        ).scalar_one()
        assert binding.status == source_attestations.STATUS_CONFLICT
        assert binding.person_id is None
        assert binding.method == "conflicting_source_identity_evidence"
        assert binding.confidence == 100
        assert sorted(conflict.details["candidatePersonIds"]) == sorted([alice.public_id, bob.public_id])


def test_items_with_a_non_dict_payload_are_skipped_and_non_matching_anchors_are_ignored():
    with db.session_scope() as session:
        anchor_person = _stable_person(session, "Anchor Person", "90", "anchoruser", "900")
        match_person = _stable_person(session, "Match Person", "93", "matchuser", "930")
        _canonical(session, "broken-tool")
        _canonical(session, "no-match-tool")
        source = ToolinfoSource(
            url="https://broken.example/toolinfo.json",
            source_kind="self_hosted_toolinfo",
            status="valid",
            valid=True,
        )
        session.add(source)
        session.flush()
        session.add(
            ToolinfoSourceItem(
                source_id=source.id,
                source_url=source.url,
                tool_name="broken-tool",
                title="Broken",
                tool_url="https://broken.example",
                payload=["not", "a", "dict"],
            )
        )
        session.add(
            ToolinfoSourceItem(
                source_id=source.id,
                source_url=source.url,
                tool_name="no-match-tool",
                title="No Match",
                tool_url="https://no-match.example",
                payload={
                    "name": "no-match-tool",
                    "title": "No Match",
                    "description": "No Match",
                    "url": "https://no-match.example",
                    "author": "Completely Different Name",
                },
            )
        )
        session.flush()

        # Independent verified evidence corroborates both tools, but the
        # "broken-tool" item's payload is not a dict (it cannot be
        # inspected for author tokens at all), and "no-match-tool"'s only
        # author does not match match_person's aliases.
        people_index.replace_source_evidence(
            session,
            "broken-tool",
            "independent_verification",
            [
                {
                    "display_name": "Anchor Person",
                    "wikimedia_global_user_id": "900",
                    "relationship_type": "maintainer",
                    "method": "independent_stable_proof",
                    "evidence_key": "900",
                    "verification_status": "verified",
                    "confidence": 100,
                }
            ],
        )
        people_index.replace_source_evidence(
            session,
            "no-match-tool",
            "independent_verification",
            [
                {
                    "display_name": "Match Person",
                    "wikimedia_global_user_id": "930",
                    "relationship_type": "maintainer",
                    "method": "independent_stable_proof",
                    "evidence_key": "930",
                    "verification_status": "verified",
                    "confidence": 100,
                }
            ],
        )

        # Should not raise despite the non-dict payload, and should not
        # bind or propagate authorship for either tool.
        source_attestations.refresh_source_ids(session, [source.id])

        bindings = {
            row.normalized_label: row for row in session.execute(select(ToolinfoAuthorBinding)).scalars()
        }
        assert "no-match-tool" not in [b.evidence.get("sourceId") for b in bindings.values()]
        no_match_binding = bindings["completely different name"]
        assert no_match_binding.status == source_attestations.STATUS_UNRESOLVED
        assert no_match_binding.person_id is None

        propagated = list(
            session.execute(
                select(ToolRelationshipEvidence).where(
                    ToolRelationshipEvidence.source == source_attestations.SOURCE_AUTHOR_ATTESTATION,
                    ToolRelationshipEvidence.person_id.in_({anchor_person.id, match_person.id}),
                )
            ).scalars()
        )
        assert propagated == []


def test_refresh_tool_names_with_no_valid_names_is_a_noop():
    with db.session_scope() as session:
        result = source_attestations.refresh_tool_names(session, ["   ", ""])
        assert result == {"tools": 0, "authorEvidence": 0, "maintainerEvidence": 0}


def test_refresh_full_updates_an_existing_rules_version_marker():
    with db.session_scope() as session:
        source_attestations.refresh_full(session)  # first call: creates the ApiCacheMeta row

    with db.session_scope() as session:
        before = session.get(ApiCacheMeta, source_attestations.RULES_META_KEY)
        before_updated_at = before.updated_at

    with db.session_scope() as session:
        source_attestations.refresh_full(session)  # second call: updates the existing row

    with db.session_scope() as session:
        after = session.get(ApiCacheMeta, source_attestations.RULES_META_KEY)
        assert after.value == source_attestations.RULES_VERSION
        assert after.updated_at >= before_updated_at


def test_incremental_refresh_attests_a_newly_indexed_source():
    with db.session_scope() as session:
        source_attestations.refresh_full(session)  # establishes the rules-version marker

    with db.session_scope() as session:
        _canonical(session, "fresh-tool")
        source = _source(
            session,
            "https://fresh.example/toolinfo.json",
            [
                {
                    "name": "fresh-tool",
                    "title": "Fresh",
                    "description": "Fresh",
                    "url": "https://fresh.example",
                    "author": "Fresh Author",
                }
            ],
        )
        source_id = source.id

    with db.session_scope() as session:
        # This source was indexed after the rules-version marker was
        # established and has never been attested, so the incremental pass
        # must notice and attest it even without an explicit source id list.
        result = source_attestations.refresh_incremental(session)
        assert result["sources"] == 1
        assert result["fullAudit"] == 0
        assert session.get(ToolinfoSourceAttestation, source_id) is not None


def test_person_identity_skips_unmapped_identifier_namespaces():
    with db.session_scope() as session:
        person = _stable_person(session, "Namespaced Person", "95", "namespaced", "950")
        session.add(
            PersonIdentifier(
                person_id=person.id,
                namespace="unmapped_namespace",
                value="ignored",
                normalized_value="ignored",
                identifier_kind="handle",
                source="test_unmapped",
            )
        )
        _toolforge_member(session, person, project="namespaced-project", uid_number="95", uid="namespaced")
        _canonical(session, "namespaced-tool")
        source = _source(
            session,
            "https://namespaced-project.toolforge.org/toolinfo.json",
            [
                {
                    "name": "namespaced-tool",
                    "title": "Namespaced",
                    "description": "Namespaced",
                    "url": "https://namespaced-project.toolforge.org",
                    "author": "Someone Else",
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])

        edge = session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.source == source_attestations.SOURCE_TARGET_MEMBERSHIP
            )
        ).scalar_one()
        assert edge.person_id == person.id


def test_incremental_refresh_runs_a_full_audit_when_no_rules_marker_exists():
    with db.session_scope() as session:
        result = source_attestations.refresh_incremental(session)
        assert result["fullAudit"] == 1
        assert session.get(ApiCacheMeta, source_attestations.RULES_META_KEY) is not None


def test_incremental_refresh_runs_a_full_audit_when_policy_source_changes(monkeypatch):
    with db.session_scope() as session:
        source_attestations.refresh_full(session)

    monkeypatch.setattr(source_attestations, "RULES_VERSION", "changed-policy")
    with db.session_scope() as session:
        result = source_attestations.refresh_incremental(session)

    assert result["fullAudit"] == 1
    with db.session_scope() as session:
        assert session.get(ApiCacheMeta, source_attestations.RULES_META_KEY).value == "changed-policy"


def test_incremental_refresh_reprocesses_sources_touched_by_identity_changes():
    with db.session_scope() as session:
        person = _stable_person(session, "Refreshed Person", "80", "refreshed", "800")
        _canonical(session, "identity-tool")
        source = _source(
            session,
            "https://identity.example/toolinfo.json",
            [
                {
                    "name": "identity-tool",
                    "title": "Identity",
                    "description": "Identity",
                    "url": "https://identity.example",
                    "author": "Refreshed Person",
                }
            ],
        )
        source_attestations.refresh_source_ids(session, [source.id])
        source_attestations.refresh_full(session)  # establishes the rules-version marker
        source_id = source.id
        person_id = person.id

    cutoff = utcnow() - timedelta(minutes=1)
    with db.session_scope() as session:
        identifier = session.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.person_id == person_id,
                PersonIdentifier.namespace == people_index.NS_WIKI_USERNAME,
            )
        ).scalar_one()
        identifier.updated_at = utcnow()

    with db.session_scope() as session:
        result = source_attestations.refresh_incremental(session, identity_changed_since=cutoff)
        assert result["sources"] >= 1
        assert result["fullAudit"] == 0
        assert session.get(ToolinfoSourceAttestation, source_id) is not None
