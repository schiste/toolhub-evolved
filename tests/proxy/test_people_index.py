# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct coverage of backend.people_index branches not reached by other suites.

people_index is exercised broadly from test_people_reconcile.py,
test_registry_candidates.py, test_people_corroborated_handles.py, and the
people-graph tests in test_backend.py. This file targets the specific
edge branches those integration-style tests never hit: identity-conflict
refusals, blank-input guards, and directory filter/order combinations that
no HTTP-route test happens to exercise.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index  # noqa: E402
from backend.models import (  # noqa: E402
    ActivityRow,
    CanonicalToolCache,
    CatalogFacetValue,
    Person,
    PersonActivitySummary,
    PersonIdentifier,
    ToolAssetCache,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
    User,
    utcnow,
)
from backend.sync import (  # noqa: E402
    AUTHOR_CLAIM_STALE,
    AUTHOR_CLAIM_UNVERIFIED,
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
    SYNC_OFFICIAL,
)


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _relationship(tool_name, person_id, *, role=PERSON_REL_AUTHOR, status=AUTHOR_CLAIM_VERIFIED, confidence=100):
    return ToolPersonRelationship(
        tool_name=tool_name,
        person_id=person_id,
        relationship_type=role,
        verification_status=status,
        confidence=confidence,
        evidence_count=1,
    )


def test_ensure_person_never_moves_a_stable_identifier_it_does_not_own():
    """A stable identifier collision must never be silently reassigned.

    Both a Wikimedia global id and a Toolforge uid_number are supplied
    together, already owned by two different people. ensure_person's
    candidate order picks the wikimedia owner; the toolforge_uid_number
    identifier belonging to the other person must be left exactly where
    it was rather than moved onto the picked person.
    """
    with db.session_scope() as s:
        person_a = people_index.ensure_person(s, display_name="A", wikimedia_global_user_id="G1", source="test")
        person_b = people_index.ensure_person(s, display_name="B", toolforge_uid_number="U1", source="test")

        resolved = people_index.ensure_person(
            s,
            display_name="A",
            wikimedia_global_user_id="G1",
            toolforge_uid_number="U1",
            source="test",
        )

        assert resolved.id == person_a.id
        identifier = s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace == people_index.NS_TOOLFORGE_UID_NUMBER,
                PersonIdentifier.normalized_value == "u1",
            )
        ).scalar_one()
        assert identifier.person_id == person_b.id


def test_ensure_person_repairs_display_name_quality_when_a_handle_is_already_registered():
    """A pre-existing current handle identifier upgrades a stale quality label.

    This models a data state that should not normally arise but is worth
    being defensive about: a person whose identity_quality was never
    updated to reflect a handle it already holds. Calling ensure_person
    with that same handle repairs the denormalized quality in place.
    """
    with db.session_scope() as s:
        person = Person(canonical_key="display:pat", display_name="Pat", identity_quality="display_name")
        s.add(person)
        s.flush()
        s.add(
            PersonIdentifier(
                person_id=person.id,
                namespace=people_index.NS_WIKI_USERNAME,
                value="Pat",
                normalized_value="pat",
                identifier_kind=people_index.IDENTIFIER_HANDLE,
                source="test",
            )
        )
        s.flush()

        resolved = people_index.ensure_person(s, display_name="Pat", wiki_username="Pat", source="test")

        assert resolved.id == person.id
        assert resolved.identity_quality == "handle"


def test_ensure_official_account_person_refuses_conflicting_stable_owners():
    with db.session_scope() as s:
        people_index.ensure_person(s, display_name="A", toolhub_user_id="1", source="test")
        people_index.ensure_person(s, display_name="B", wikimedia_global_user_id="G9", source="test")

        result = people_index.ensure_official_account_person(
            s,
            toolhub_user_id="1",
            wikimedia_global_user_id="G9",
            username="conflict",
        )

        assert result is None


def test_attach_verified_external_account_refuses_a_blank_or_unknown_stable_id():
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Casey", source="test")

        assert (
            people_index.attach_verified_external_account(
                s,
                person,
                stable_namespace=people_index.NS_TOOLHUB_USER_ID,
                stable_id="",
                source="test",
            )
            is False
        )
        assert (
            people_index.attach_verified_external_account(
                s,
                person,
                stable_namespace="not_a_real_namespace",
                stable_id="123",
                source="test",
            )
            is False
        )


def test_attach_verified_external_account_refuses_an_id_owned_by_someone_else():
    with db.session_scope() as s:
        owner = people_index.ensure_person(s, display_name="Owner", toolhub_user_id="1", source="test")
        other = people_index.ensure_person(s, display_name="Other", source="test")

        result = people_index.attach_verified_external_account(
            s,
            other,
            stable_namespace=people_index.NS_TOOLHUB_USER_ID,
            stable_id="1",
            source="test",
        )

        assert result is False
        assert owner.id != other.id


def test_attach_verified_external_account_without_a_handle_attaches_only_the_stable_id():
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Casey", source="test")

        result = people_index.attach_verified_external_account(
            s,
            person,
            stable_namespace=people_index.NS_TOOLHUB_USER_ID,
            stable_id="55",
            source="test",
        )

        assert result is True
        assert person.identity_quality == "stable"
        handles = list(
            s.execute(
                select(PersonIdentifier).where(
                    PersonIdentifier.person_id == person.id,
                    PersonIdentifier.identifier_kind == people_index.IDENTIFIER_HANDLE,
                )
            ).scalars()
        )
        assert handles == []


def test_corroborated_handle_person_rejects_a_blank_label():
    with db.session_scope() as s:
        assert people_index.corroborated_handle_person(s, tool_name="toolx", display_name="   ", source="test") is None


def test_replace_source_evidence_skips_observations_with_no_identity_and_no_label():
    with db.session_scope() as s:
        rows = people_index.replace_source_evidence(s, "toolx", "sourcex", [{"relationship_type": PERSON_REL_AUTHOR}])

        assert rows == []
        assert s.query(ToolRelationshipEvidence).count() == 0
        assert s.query(UnresolvedAttributionEvidence).count() == 0


def test_resolve_tool_relationships_marks_wholly_expired_evidence_as_stale():
    with db.session_scope() as s:
        past = utcnow() - timedelta(days=1)
        people_index.replace_source_evidence(
            s,
            "toolx",
            "sourcex",
            [
                {
                    "display_name": "Ada",
                    "wiki_username": "Ada",
                    "relationship_type": PERSON_REL_AUTHOR,
                    "verification_status": AUTHOR_CLAIM_VERIFIED,
                    "expires_at": past,
                }
            ],
        )

        relationship = s.query(ToolPersonRelationship).filter_by(tool_name="toolx").one()
        assert relationship.verification_status == AUTHOR_CLAIM_STALE


def test_verified_at_tracks_status_transitions_not_ordinary_reprojection():
    observation = {
        "display_name": "Ada",
        "wiki_username": "Ada",
        "relationship_type": PERSON_REL_AUTHOR,
        "verification_status": AUTHOR_CLAIM_VERIFIED,
    }
    with db.session_scope() as s:
        people_index.replace_source_evidence(s, "toolx", "sourcex", [observation])
        relationship = s.query(ToolPersonRelationship).filter_by(tool_name="toolx").one()
        first_verified_at = relationship.verified_at
        people_index.replace_source_evidence(s, "toolx", "sourcex", [observation])
        assert relationship.verified_at == first_verified_at

        people_index.replace_source_evidence(
            s,
            "toolx",
            "sourcex",
            [{**observation, "verification_status": AUTHOR_CLAIM_UNVERIFIED}],
        )
        assert relationship.verified_at is None
        people_index.replace_source_evidence(s, "toolx", "sourcex", [observation])
        assert relationship.verified_at is not None
        assert relationship.verified_at >= first_verified_at


def test_search_unresolved_attributions_filters_by_project_and_role():
    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s, "toolp", "sourcep", [{"display_name": "Lonely", "relationship_type": PERSON_REL_AUTHOR}]
        )
        people_index.replace_source_evidence(
            s, "toolq", "sourceq", [{"display_name": "Lonely", "relationship_type": PERSON_REL_MAINTAINER}]
        )
        s.add(CatalogFacetValue(tool_name="toolp", field="wiki", value="enwiki", label="English Wikipedia"))
        s.flush()

        result = people_index.search_unresolved_attributions(
            s,
            people_index.UnresolvedAttributionQuery(project="ENWIKI", role=PERSON_REL_AUTHOR),
        )

        assert result["count"] == 1
        assert result["results"][0]["label"] == "Lonely"
        assert result["results"][0]["relationshipBreakdown"] == [
            {
                "type": PERSON_REL_AUTHOR,
                "status": AUTHOR_CLAIM_UNVERIFIED,
                "toolCount": 1,
                "evidenceCount": 1,
                "bestConfidence": 0,
            }
        ]


def test_resolve_legacy_handle_rejects_a_blank_query():
    with db.session_scope() as s:
        result = people_index.resolve_legacy_handle(s, "   ")

        assert result == {"status": "not_found", "query": "", "matchType": "none", "candidates": []}


def test_public_people_summary_skips_relationships_whose_person_is_not_publishable():
    """A relationship can outlive the identity evidence that would publish it.

    Nothing here deletes the relationship row, so it still counts toward the
    raw totals; it just cannot appear in the published people list, which
    only shows identities public_identity_ids currently vouches for.
    """
    with db.session_scope() as s:
        hidden = Person(canonical_key="display:hidden", display_name="Hidden", identity_quality="display_name")
        s.add(hidden)
        s.flush()
        s.add(_relationship("toolz", hidden.id))
        s.flush()

        summary = people_index.public_people_summary(s, "toolz")

        assert summary["people"] == []
        assert summary["relationshipCount"] == 1
        assert summary["resolvedRelationshipCount"] == 0


def test_public_people_summary_folds_only_same_role_exact_handle_attributions():
    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "bd808-toolhub-evolved-test",
            "repository_owner",
            [
                {
                    "display_name": "Schiste",
                    "relationship_type": PERSON_REL_MAINTAINER,
                    "verification_status": AUTHOR_CLAIM_VERIFIED,
                    "confidence": 95,
                },
                {
                    "display_name": "Schiste",
                    "relationship_type": PERSON_REL_AUTHOR,
                    "verification_status": AUTHOR_CLAIM_UNVERIFIED,
                    "confidence": 40,
                },
            ],
        )
        people_index.replace_source_evidence(
            s,
            "bd808-toolhub-evolved-test",
            "toolforge_ldap",
            [
                {
                    "display_name": "Schiste",
                    "toolforge_uid_number": "102093",
                    "toolforge_username": "Schiste",
                    "relationship_type": PERSON_REL_MAINTAINER,
                    "verification_status": AUTHOR_CLAIM_UNVERIFIED,
                    "confidence": 60,
                }
            ],
        )

        summary = people_index.public_people_summary(s, "bd808-toolhub-evolved-test")

        assert summary["counts"][PERSON_REL_MAINTAINER] == 1
        assert summary["people"][0]["relationships"][0]["status"] == AUTHOR_CLAIM_UNVERIFIED
        assert summary["foldedUnresolvedAttributionCount"] == 1
        assert summary["unresolvedAttributions"][0]["relationshipTypes"] == [PERSON_REL_AUTHOR]
        assert summary["unresolvedCounts"] == {PERSON_REL_AUTHOR: 1, PERSON_REL_MAINTAINER: 0}


def test_person_detail_includes_a_cached_icon_url_when_the_asset_is_ready():
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Ada", toolhub_user_id="9", source="test")
        s.add(_relationship("toolz", person.id))
        s.add(
            CanonicalToolCache(
                tool_name="toolz",
                record={"name": "toolz", "title": "Tool Z"},
                expires_at=utcnow() + timedelta(days=1),
                stale_until=utcnow() + timedelta(days=1),
            )
        )
        s.add(ToolAssetCache(tool_name="toolz", status="ready"))
        s.flush()

        detail = people_index.person_detail(s, person.public_id)

        assert detail["tools"]["results"][0]["summary"]["_cachedIconUrl"] == "/v1/catalog/tools/toolz/icon/"


def test_person_detail_returns_none_for_an_unknown_or_unpublishable_id():
    with db.session_scope() as s:
        assert people_index.person_detail(s, "not-a-real-id") is None

        hidden = Person(canonical_key="display:hidden2", display_name="Hidden", identity_quality="display_name")
        s.add(hidden)
        s.flush()

        assert people_index.person_detail(s, hidden.public_id) is None


def test_search_people_directory_filters_by_unverified_status():
    with db.session_scope() as s:
        verified = people_index.ensure_person(s, display_name="Verified", toolhub_user_id="1", source="test")
        unverified = people_index.ensure_person(s, display_name="Unverified", toolhub_user_id="2", source="test")
        s.add(_relationship("toolv", verified.id, status=AUTHOR_CLAIM_VERIFIED, confidence=100))
        s.add(_relationship("toolu", unverified.id, status=AUTHOR_CLAIM_UNVERIFIED, confidence=10))
        s.flush()

        result = people_index.search_people_directory(s, people_index.PeopleDirectoryQuery(verification="unverified"))

        ids = {item["id"] for item in result["results"]}
        assert ids == {unverified.public_id}


def test_search_people_directory_filters_people_with_unknown_activity():
    with db.session_scope() as s:
        active = people_index.ensure_person(s, display_name="Active", toolhub_user_id="3", source="test")
        unknown = people_index.ensure_person(s, display_name="Unknown", toolhub_user_id="4", source="test")
        s.add(_relationship("toola", active.id))
        s.add(_relationship("toolb", unknown.id))
        user = User(wm_sub="u3", username="active-user", person_id=active.id)
        s.add(user)
        s.flush()
        s.add(
            ActivityRow(
                kind="revisions",
                client_id="c1",
                user_id=user.id,
                object_type="tool",
                official_status=SYNC_OFFICIAL,
                row={},
            )
        )
        s.flush()
        people_index.refresh_activity_summaries(s, person_ids={active.id, unknown.id})
        s.flush()

        result = people_index.search_people_directory(s, people_index.PeopleDirectoryQuery(activity="unknown"))

        ids = {item["id"] for item in result["results"]}
        assert unknown.public_id in ids
        assert active.public_id not in ids


def test_search_people_directory_orders_by_recent_and_by_relationship():
    with db.session_scope() as s:
        older = people_index.ensure_person(s, display_name="Older", toolhub_user_id="5", source="test")
        newer = people_index.ensure_person(s, display_name="Newer", toolhub_user_id="6", source="test")
        s.add(_relationship("toolo", older.id, confidence=50))
        s.add(_relationship("tooln", newer.id, confidence=90))
        s.add(
            PersonActivitySummary(
                person_id=older.id,
                related_tool_count=1,
                verified_tool_count=1,
                last_contribution_at=utcnow() - timedelta(days=10),
                activity_status="active",
            )
        )
        s.add(
            PersonActivitySummary(
                person_id=newer.id,
                related_tool_count=1,
                verified_tool_count=1,
                last_contribution_at=utcnow(),
                activity_status="active",
            )
        )
        s.flush()

        recent = people_index.search_people_directory(s, people_index.PeopleDirectoryQuery(ordering="recent"))
        by_relationship = people_index.search_people_directory(
            s, people_index.PeopleDirectoryQuery(ordering="relationship")
        )

        assert [item["id"] for item in recent["results"]] == [newer.public_id, older.public_id]
        assert {item["id"] for item in by_relationship["results"]} == {older.public_id, newer.public_id}


def test_relationship_directory_filter_ignores_an_unknown_verification_value():
    clause = people_index._relationship_directory_filter(
        role="", verification="everything", project="", checked_at=utcnow()
    )
    assert clause is not None
