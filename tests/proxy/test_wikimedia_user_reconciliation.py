# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic Wikimedia user-space author reconciliation."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, wikimedia_user_reconciliation  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    PersonAccountBinding,
    PersonIdentifier,
    ToolforgeAccountProjection,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    utcnow,
)


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def _canonical(session, name="enwiki-enterprisey-tool", *, url=None, author="Enterprisey"):
    now = utcnow()
    session.add(
        CanonicalToolCache(
            tool_name=name,
            record={
                "name": name,
                "url": url or "https://en.wikipedia.org/wiki/User:Enterprisey/tool.js",
                "author": [{"name": author}],
            },
            source_url=f"https://toolhub.wikimedia.org/api/tools/{name}/",
            expires_at=now,
            stale_until=now,
        )
    )


def _account(session, *, username="Enterprisey", uid_number="9001", disabled=False):
    session.add(
        ToolforgeAccountProjection(
            uid_number=uid_number,
            uid=username.casefold(),
            normalized_uid=username.casefold(),
            developer_username=username,
            normalized_developer_username=username.casefold(),
            disabled=disabled,
        )
    )


def _wikimedia_person(session, *, username="Enterprisey", global_id="500"):
    return people_index.ensure_person(
        session,
        display_name=username,
        wikimedia_global_user_id=global_id,
        wiki_username=username,
        source="wikimedia_centralauth",
    )


def test_three_way_match_verifies_the_author_and_maintainer_then_binds_the_account():
    with db.session_scope() as session:
        _canonical(session)
        _account(session)
        person = _wikimedia_person(session)
        person_id = person.id

        result = wikimedia_user_reconciliation.synchronize(session)

        assert result["candidateTools"] == 1
        assert result["verifiedTools"] == 1
        assert result["authorEvidence"] == 1
        assert result["maintainerEvidence"] == 1
        assert result["accountsBound"] == 1
        binding = session.query(PersonAccountBinding).one()
        assert binding.status == "verified"
        assert binding.person_id == person_id
        assert binding.proof_method == wikimedia_user_reconciliation.PROOF_METHOD
        edges = {row.relationship_type: row for row in session.query(ToolRelationshipEvidence).all()}
        assert set(edges) == {"author", "maintainer"}
        assert all(edge.verification_status == "verified" for edge in edges.values())
        assert all(edge.person_id == person_id for edge in edges.values())
        assert edges["maintainer"].method == wikimedia_user_reconciliation.MAINTAINER_METHOD
        assert edges["maintainer"].evidence_payload["wikimediaPageOwner"] == "Enterprisey"
        assert edges["author"].evidence_payload["matchedAuthor"] == "Enterprisey"
        assert edges["author"].evidence_payload["toolforgeDeveloperUsername"] == "Enterprisey"
        relationships = {row.relationship_type: row for row in session.query(ToolPersonRelationship).all()}
        assert set(relationships) == {"author", "maintainer"}
        assert all(row.verification_status == "verified" for row in relationships.values())
        identifiers = {
            (row.namespace, row.value)
            for row in session.query(PersonIdentifier).filter_by(person_id=person_id, is_current=True)
        }
        assert (people_index.NS_TOOLFORGE_UID_NUMBER, "9001") in identifiers
        assert (people_index.NS_TOOLFORGE_USERNAME, "Enterprisey") in identifiers


@pytest.mark.parametrize(
    ("url", "author", "account_name", "disabled", "expected_roles"),
    [
        (
            "https://en.wikipedia.org.attacker.example/wiki/User:Enterprisey/tool.js",
            "Enterprisey",
            "Enterprisey",
            False,
            set(),
        ),
        (
            "https://en.wikipedia.org/wiki/User:SomeoneElse/tool.js",
            "Enterprisey",
            "Enterprisey",
            False,
            set(),
        ),
        (
            "https://en.wikipedia.org/wiki/User:Enterprisey/tool.js",
            "SomeoneElse",
            "Enterprisey",
            False,
            {"maintainer"},
        ),
        (
            "https://en.wikipedia.org/wiki/User:Enterprisey/tool.js",
            "Enterprisey",
            "DifferentAccount",
            False,
            set(),
        ),
        (
            "https://en.wikipedia.org/wiki/User:Enterprisey/tool.js",
            "Enterprisey",
            "Enterprisey",
            True,
            set(),
        ),
    ],
)
def test_each_role_requires_its_own_complete_evidence(url, author, account_name, disabled, expected_roles):
    with db.session_scope() as session:
        _canonical(session, url=url, author=author)
        _account(session, username=account_name, disabled=disabled)
        _wikimedia_person(session)

        result = wikimedia_user_reconciliation.synchronize(session)

        roles = {row.relationship_type for row in session.query(ToolRelationshipEvidence).all()}
        assert roles == expected_roles
        assert result["verifiedTools"] == int(bool(expected_roles))
        assert result["authorEvidence"] == int("author" in expected_roles)
        assert result["maintainerEvidence"] == int("maintainer" in expected_roles)
        assert session.query(PersonAccountBinding).count() == int(bool(expected_roles))


def test_a_stable_toolforge_identity_conflict_never_publishes_authorship():
    with db.session_scope() as session:
        _canonical(session)
        _account(session)
        expected = _wikimedia_person(session)
        conflicting = people_index.ensure_person(
            session,
            display_name="Conflicting",
            toolforge_uid_number="9001",
            source="test_conflict",
        )
        session.add(
            PersonAccountBinding(
                provider="toolforge",
                external_id="9001",
                person_id=conflicting.id,
                status="verified",
                proof_method="existing_stable_proof",
                confidence=100,
            )
        )

        result = wikimedia_user_reconciliation.synchronize(session)

        assert result["bindingConflicts"] == 1
        assert session.query(ToolRelationshipEvidence).count() == 0
        assert expected.id != conflicting.id


def test_changed_canonical_ownership_retires_previous_evidence_and_cache_is_idempotent():
    with db.session_scope() as session:
        _canonical(session)
        _account(session)
        _wikimedia_person(session)
        first = wikimedia_user_reconciliation.synchronize(session)
        second = wikimedia_user_reconciliation.synchronize(session)
        assert first["verifiedTools"] == 1
        assert second["cacheHit"] == 1

        tool = session.get(CanonicalToolCache, "enwiki-enterprisey-tool")
        tool.record = dict(tool.record) | {"url": "https://en.wikipedia.org/wiki/User:SomeoneElse/tool.js"}
        retired = wikimedia_user_reconciliation.synchronize(session)

        assert retired["retiredTools"] == 1
        evidence = session.query(ToolRelationshipEvidence).all()
        assert len(evidence) == 2
        assert all(row.withdrawn_at is not None for row in evidence)
        assert session.query(ToolPersonRelationship).count() == 0
