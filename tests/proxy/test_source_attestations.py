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
    CanonicalToolCache,
    PersonAccountBinding,
    PersonReconciliationConflict,
    PersonReconciliationRun,
    ToolRelationshipEvidence,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolinfoAuthorBinding,
    ToolinfoSource,
    ToolinfoSourceAttestation,
    ToolinfoSourceGeneration,
    ToolinfoSourceItem,
    UnresolvedAttributionEvidence,
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
