# SPDX-License-Identifier: GPL-3.0-or-later
"""Registry-resolved labels become candidates and publish only when corroborated."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, people_policy, people_reconcile  # noqa: E402
from backend.models import (  # noqa: E402
    PersonIdentifier,
    PersonReconciliationMapping,
    PersonReconciliationRun,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
)
from backend.public_identity import WikimediaIdentity  # noqa: E402
from backend.sync import AUTHOR_CLAIM_UNVERIFIED, AUTHOR_CLAIM_VERIFIED, PERSON_REL_AUTHOR  # noqa: E402


class FakeRegistry:
    """Resolve only the usernames it was told about, recording every lookup."""

    def __init__(self, accounts):
        self.accounts = accounts
        self.asked = []

    def lookup_username(self, username):
        self.asked.append(username)
        global_id = self.accounts.get(username)
        return WikimediaIdentity(global_user_id=global_id, username=username) if global_id else None


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _run(session):
    row = PersonReconciliationRun(mode="apply", status="running")
    session.add(row)
    session.flush()
    return row


def _label_person(session, label, tool, *, status=AUTHOR_CLAIM_UNVERIFIED):
    """A display-only observation: the state every unresolved label is in."""
    person = people_index.ensure_person(session, display_name=label, source="toolhub_author_metadata")
    session.add(
        ToolRelationshipEvidence(
            tool_name=tool,
            person_id=person.id,
            relationship_type=PERSON_REL_AUTHOR,
            source="toolhub_author_metadata",
            verification_status=status,
        )
    )
    session.add(
        ToolPersonRelationship(
            tool_name=tool, person_id=person.id, relationship_type=PERSON_REL_AUTHOR, verification_status=status
        )
    )
    session.flush()
    return person


def _stable_person(session, name, global_id):
    return people_index.ensure_person(
        session, display_name=name, wikimedia_global_user_id=global_id, source="toolhub_oauth"
    )


def _discover(session, registry, **kwargs):
    return people_reconcile.discover_registry_candidates(
        session, run_id=_run(session).id, provider=registry, sleep=lambda _s: None, **kwargs
    )


def _mapping(session, source_id):
    return (
        session.query(PersonReconciliationMapping)
        .filter_by(source_person_id=source_id)
        .order_by(PersonReconciliationMapping.id.desc())
        .first()
    )


def test_an_uncorroborated_match_is_a_candidate_and_moves_no_evidence():
    with db.session_scope() as session:
        source = _label_person(session, "0xDeadbeef", "toolx")
        target = _stable_person(session, "Real Person", "4242")
        registry = FakeRegistry({"0xDeadbeef": "4242"})

        result = _discover(session, registry)
        mapping = _mapping(session, source.id)

        assert result["resolved"] == 1
        assert mapping.decision == people_reconcile.MAPPING_CANDIDATE
        assert mapping.reason == people_policy.REASON_REGISTRY_HANDLE
        # The account exists; that says nothing about who wrote the tool, so
        # the evidence stays exactly where it was.
        evidence = session.query(ToolRelationshipEvidence).filter_by(tool_name="toolx").one()
        assert evidence.person_id == source.id
        assert target.id != evidence.person_id


def test_a_corroborated_match_links_and_moves_the_evidence():
    with db.session_scope() as session:
        source = _label_person(session, "0xDeadbeef", "toolx")
        target = _stable_person(session, "Real Person", "4242")
        # Independent verified evidence tying the target to the same tool.
        session.add(
            ToolRelationshipEvidence(
                tool_name="toolx",
                person_id=target.id,
                relationship_type=PERSON_REL_AUTHOR,
                source="toolforge_toolsadmin",
                method="toolforge_maintainer",
                verification_status=AUTHOR_CLAIM_VERIFIED,
            )
        )
        session.flush()
        registry = FakeRegistry({"0xDeadbeef": "4242"})

        result = _discover(session, registry)
        mapping = _mapping(session, source.id)

        assert result["linked"] == 1
        assert mapping.decision == people_reconcile.MAPPING_AUTO_LINK
        assert mapping.reason == people_policy.REASON_HANDLE_CORROBORATED
        assert session.query(ToolRelationshipEvidence).filter_by(person_id=source.id).count() == 0


def test_name_shaped_labels_are_never_sent_to_the_registry():
    with db.session_scope() as session:
        _label_person(session, "Aaron Liu", "toolx")
        registry = FakeRegistry({"Aaron Liu": "4242"})

        result = _discover(session, registry)

        # The gate runs before the lookup, so a name is never even asked about.
        assert registry.asked == []
        assert result["checked"] == 0


def test_an_unknown_account_resolves_nothing():
    with db.session_scope() as session:
        source = _label_person(session, "0xDeadbeef", "toolx")
        result = _discover(session, FakeRegistry({}))

        assert result["resolved"] == 0
        assert _mapping(session, source.id) is None


def test_a_resolved_account_absent_from_the_graph_is_created_as_a_person():
    with db.session_scope() as session:
        source = _label_person(session, "0xDeadbeef", "toolx")
        # CentralAuth knows the account and no person here holds that id yet.
        result = _discover(session, FakeRegistry({"0xDeadbeef": "9999"}))
        created = (
            session.query(PersonIdentifier)
            .filter_by(namespace=people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, value="9999")
            .one_or_none()
        )

        assert result["resolved"] == 1
        assert result["peopleCreated"] == 1
        # The identity is recorded from an immutable global id, but the tool
        # relationship still has to be earned: the mapping is a candidate and
        # the label's evidence has not moved.
        assert _mapping(session, source.id).decision == people_reconcile.MAPPING_CANDIDATE
        assert session.query(ToolRelationshipEvidence).filter_by(person_id=source.id).count() == 1
        assert created is not None


def test_a_person_created_this_way_stays_out_of_the_public_directory():
    with db.session_scope() as session:
        _label_person(session, "0xDeadbeef", "toolx")
        _discover(session, FakeRegistry({"0xDeadbeef": "9999"}))
        session.flush()
        listed = people_index.search_people_directory(session, people_index.PeopleDirectoryQuery(query="0xDeadbeef"))

    # Publishable by stable identity, but with no tool relationship it is not
    # listed, so a mistaken lookup never becomes a visible claim about anyone.
    assert listed["count"] == 0


def test_creating_the_same_account_twice_does_not_duplicate_it():
    with db.session_scope() as session:
        _label_person(session, "0xDeadbeef", "toolx")
        _label_person(session, "0xdeadbeef2", "tooly")
        registry = FakeRegistry({"0xDeadbeef": "9999", "0xdeadbeef2": "9999"})

        result = _discover(session, registry)

        assert result["resolved"] == 2
        assert result["peopleCreated"] == 1


def test_lookups_are_bounded_per_run():
    with db.session_scope() as session:
        for index in range(8):
            _label_person(session, f"handle{index}", f"tool{index}")
        registry = FakeRegistry({})

        _discover(session, registry, label_limit=3)

        assert len(registry.asked) == 3
