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
    PERSON_REL_CATALOG_ACTOR,
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


def test_person_slug_is_readable_immutable_and_extends_only_on_collision():
    with db.session_scope() as s:
        first = Person(
            canonical_key="stable:first",
            public_id="31e9abd5-fb61-42d8-96e4-ccbe3bb54ced",
            display_name="Christophe",
        )
        people_index.ensure_person_public_slug(s, first)
        s.add(first)
        s.flush()

        second = Person(
            canonical_key="stable:second",
            public_id="11111111-1111-1111-1111-11113bb54ced",
            display_name="Christophe",
        )
        people_index.ensure_person_public_slug(s, second)
        s.add(second)
        s.flush()

        assert first.public_slug == "christophe-4ced"
        assert second.public_slug == "christophe-b54ced"
        first.display_name = "Christophe Renamed"
        assert people_index.ensure_person_public_slug(s, first) == "christophe-4ced"


def test_person_slug_preserves_unicode_names_and_has_an_empty_name_fallback():
    assert people_index.person_slug_candidates("Élodie 张", "00000000-0000-0000-0000-00000000ab12")[0] == "élodie-张-ab12"
    assert people_index.person_slug_candidates("---", "00000000-0000-0000-0000-00000000ab12")[0] == "person-ab12"


def test_person_slug_handles_non_alphanumeric_and_short_public_ids():
    hashed = people_index.person_slug_candidates("Ada", "---")
    short = people_index.person_slug_candidates("Ada", "a")

    assert hashed[0].startswith("ada-")
    assert short == ("ada-a",)


def test_slug_assignment_generates_missing_ids_and_has_a_collision_fallback():
    class AvailableSession:
        @staticmethod
        def scalar(_statement):
            return None

    missing = Person(canonical_key="missing", public_id="", display_name="Ada")
    assert people_index.ensure_person_public_slug(AvailableSession(), missing).startswith("ada-")
    assert missing.public_id

    class CollidingSession:
        @staticmethod
        def scalar(_statement):
            return 1

    colliding = Person(canonical_key="collision", public_id="fixed-public-id", display_name="Ada")
    slug = people_index.ensure_person_public_slug(CollidingSession(), colliding)
    assert slug.startswith("ada-")
    assert len(slug.rsplit("-", 1)[1]) == 32


def test_public_handle_owners_exclude_handle_only_people():
    with db.session_scope() as session:
        people_index.ensure_person(session, display_name="Ghost", wiki_username="Ghost", source="test")

        assert people_index._unique_public_handle_owners(session, {"ghost"}) == {}  # noqa: SLF001


def test_candidate_projections_skip_existing_relationships_and_tools_outside_the_page():
    with db.session_scope() as session:
        person = people_index.ensure_person(
            session,
            display_name="Ada",
            wikimedia_global_user_id="42",
            wiki_username="Ada",
            source="test",
        )
        for tool_name in ("a-tool", "b-tool"):
            people_index.replace_source_evidence(
                session,
                tool_name,
                "toolhub_author_metadata",
                [
                    {
                        "display_name": "Ada",
                        "relationship_type": PERSON_REL_AUTHOR,
                        "verification_status": AUTHOR_CLAIM_UNVERIFIED,
                        "confidence": 45,
                    }
                ],
            )
        session.add(_relationship("a-tool", person.id))
        session.flush()

        detail = people_index.person_detail(
            session,
            person.public_id,
            people_index.PersonToolPage(page=1, page_size=1),
        )
        summaries = people_index._directory_relationship_summaries(  # noqa: SLF001
            session,
            {person.id},
            checked_at=utcnow(),
        )

        assert detail["tools"]["count"] == 2
        assert detail["tools"]["results"][0]["name"] == "a-tool"
        assert summaries[person.id]["toolCountsByType"][PERSON_REL_AUTHOR] == 2


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


def test_public_people_summary_projects_current_exact_handle_attributions_once():
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
        assert summary["counts"][PERSON_REL_AUTHOR] == 1
        assert summary["people"][0]["relationships"][0]["status"] == AUTHOR_CLAIM_UNVERIFIED
        assert summary["people"][0]["relationships"][1]["candidateOnly"] is True
        assert summary["foldedUnresolvedAttributionCount"] == 2
        assert summary["unresolvedAttributions"] == []
        assert summary["unresolvedCounts"] == {PERSON_REL_AUTHOR: 0, PERSON_REL_MAINTAINER: 0}


def test_unique_current_handle_attribution_uses_one_canonical_person_profile():
    with db.session_scope() as s:
        person = people_index.ensure_person(
            s,
            display_name="Christophe",
            wikimedia_global_user_id="36969602",
            wiki_username="Christophe",
            source="test",
        )
        people_index.replace_source_evidence(
            s,
            "current-tool",
            "toolhub_author_metadata",
            [
                {
                    "display_name": "Christophe",
                    "relationship_type": PERSON_REL_AUTHOR,
                    "verification_status": AUTHOR_CLAIM_UNVERIFIED,
                    "confidence": 45,
                }
            ],
        )

        resolution = people_index.resolve_legacy_handle(s, "Christophe", attribution_context=True)
        summary = people_index.public_people_summary(s, "current-tool")
        detail = people_index.person_detail(s, person.public_id)
        directory = people_index.search_people_directory(
            s,
            people_index.PeopleDirectoryQuery(query="Christophe"),
        )

        assert resolution["status"] == "resolved"
        assert resolution["person"]["id"] == person.public_id
        assert summary["unresolvedAttributions"] == []
        assert summary["foldedUnresolvedAttributionCount"] == 1
        assert summary["people"][0]["id"] == person.public_id
        candidate = summary["people"][0]["relationships"][0]
        assert candidate["type"] == PERSON_REL_AUTHOR
        assert candidate["status"] == AUTHOR_CLAIM_UNVERIFIED
        assert candidate["confidence"] == 45
        assert candidate["candidateOnly"] is True
        assert detail["toolCount"] == 1
        assert detail["activity"]["relatedToolCount"] == 1
        assert detail["tools"]["results"][0]["name"] == "current-tool"
        assert detail["tools"]["results"][0]["relationships"][0]["candidateOnly"] is True
        assert directory["results"][0]["relationshipSummary"]["toolCountsByType"][PERSON_REL_AUTHOR] == 1


def test_public_people_projections_exclude_stale_and_expired_attributions():
    with db.session_scope() as s:
        person = people_index.ensure_person(
            s,
            display_name="Ada",
            wikimedia_global_user_id="42",
            wiki_username="Ada",
            source="test",
        )
        s.add(_relationship("past-tool", person.id, status=AUTHOR_CLAIM_STALE, confidence=80))
        people_index.replace_source_evidence(
            s,
            "expired-tool",
            "toolhub_author_metadata",
            [
                {
                    "display_name": "Ada",
                    "relationship_type": PERSON_REL_AUTHOR,
                    "verification_status": AUTHOR_CLAIM_UNVERIFIED,
                    "confidence": 45,
                    "expires_at": utcnow() - timedelta(minutes=1),
                }
            ],
        )
        s.flush()

        assert people_index.public_people_summary(s, "past-tool")["people"] == []
        assert people_index.public_people_summary(s, "expired-tool")["people"] == []
        assert (
            people_index.search_unresolved_attributions(
                s,
                people_index.UnresolvedAttributionQuery(query="Ada"),
            )["results"]
            == []
        )
        assert people_index.person_detail(s, person.public_id)["toolCount"] == 0


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


def test_handle_owner_ids_rejects_a_blank_handle():
    # A blank handle is not a handle nobody holds, it is not a question. Left
    # unguarded the normalized column would be matched against "", which every
    # identifier written without one would answer.
    with db.session_scope() as s:
        person = people_index.ensure_person(
            s, display_name="Ada", wiki_username="Ada", wikimedia_global_user_id="42", source="test"
        )
        s.flush()

        assert people_index.handle_owner_ids(s, "Ada") == {person.id}
        assert people_index.handle_owner_ids(s, "   ") == set()


def test_promoting_an_unresolved_observation_refuses_a_blank_label():
    # The stored label is the whole observation here, so a blank one names
    # nobody and there is nothing to re-decide.
    with db.session_scope() as s:
        row = UnresolvedAttributionEvidence(tool_name="toolx", observed_label="   ")

        assert people_index.promote_unresolved_attribution(s, row) is None


def test_refreshing_an_unchanged_summary_writes_nothing():
    # Restamping computed_at on every pass is what made this table write-hot:
    # the busiest person is attached to most of the catalog, so nearly every
    # refresh queued an UPDATE carrying two timestamps and no new data, and
    # concurrent jobs deadlocked on that one row.
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Ida", toolhub_user_id="90", source="test")
        s.add(_relationship("toolq", person.id))
        s.flush()
        people_index.refresh_activity_summaries(s, person_ids={person.id})
        s.flush()
        first_computed_at = s.get(PersonActivitySummary, person.id).computed_at

        people_index.refresh_activity_summaries(s, person_ids={person.id})

        row = s.get(PersonActivitySummary, person.id)
        assert row not in s.dirty
        assert row.computed_at == first_computed_at


def test_refreshing_a_changed_summary_restamps_it():
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Jo", toolhub_user_id="91", source="test")
        s.add(_relationship("toolr", person.id))
        s.flush()
        people_index.refresh_activity_summaries(s, person_ids={person.id})
        s.flush()
        first_computed_at = s.get(PersonActivitySummary, person.id).computed_at

        s.add(_relationship("tools", person.id, role=PERSON_REL_MAINTAINER))
        s.flush()
        people_index.refresh_activity_summaries(s, person_ids={person.id})

        row = s.get(PersonActivitySummary, person.id)
        assert row.related_tool_count == 2
        assert row.computed_at > first_computed_at


def test_refreshing_restamps_a_summary_that_outlived_its_freshness_window():
    # computed_at still has to mean something. Skipping the write forever
    # would freeze it at the last content change, so a row that has aged past
    # the staleness window it sets for itself is restamped even unchanged.
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Kim", toolhub_user_id="92", source="test")
        s.add(_relationship("toolt", person.id))
        s.flush()
        people_index.refresh_activity_summaries(s, person_ids={person.id})
        s.flush()
        row = s.get(PersonActivitySummary, person.id)
        stale_computed_at = utcnow() - timedelta(days=people_index.ACTIVITY_STALE_DAYS + 1)
        row.computed_at = stale_computed_at
        row.stale_at = utcnow() - timedelta(seconds=1)
        s.flush()

        people_index.refresh_activity_summaries(s, person_ids={person.id})

        row = s.get(PersonActivitySummary, person.id)
        assert row.computed_at > stale_computed_at
        assert row.stale_at > utcnow()


def test_a_catalog_actor_edge_never_counts_toward_a_public_summary():
    # catalog_actor is not a published role, so an edge carrying it must not
    # move any stored count.
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="Lee", toolhub_user_id="93", source="test")
        s.add(_relationship("toolu", person.id, role=PERSON_REL_CATALOG_ACTOR))
        s.flush()

        people_index.refresh_activity_summaries(s, person_ids={person.id})

        row = s.get(PersonActivitySummary, person.id)
        assert row.related_tool_count == 0
        assert row.verified_tool_count == 0
        assert row.activity_status == "unknown"


def test_an_edge_whose_evidence_has_not_moved_is_left_alone():
    observation = {
        "display_name": "Ada",
        "wiki_username": "Ada",
        "relationship_type": PERSON_REL_AUTHOR,
        "verification_status": AUTHOR_CLAIM_VERIFIED,
    }
    with db.session_scope() as s:
        people_index.replace_source_evidence(s, "toolx", "sourcex", [observation])
        relationship = s.query(ToolPersonRelationship).filter_by(tool_name="toolx").one()
        marker = utcnow() - timedelta(days=3)
        relationship.resolved_at = marker
        relationship.updated_at = marker
        s.flush()

        people_index.replace_source_evidence(s, "toolx", "sourcex", [observation])

        # An UPDATE here would set these two columns and nothing else, which is
        # exactly the write concurrent jobs were queuing on in production.
        assert relationship.resolved_at == marker
        assert relationship.updated_at == marker


def test_an_edge_whose_evidence_moved_is_restamped():
    observation = {
        "display_name": "Ada",
        "wiki_username": "Ada",
        "relationship_type": PERSON_REL_AUTHOR,
        "verification_status": AUTHOR_CLAIM_VERIFIED,
    }
    with db.session_scope() as s:
        people_index.replace_source_evidence(s, "toolx", "sourcex", [observation])
        relationship = s.query(ToolPersonRelationship).filter_by(tool_name="toolx").one()
        marker = utcnow() - timedelta(days=3)
        relationship.resolved_at = marker
        relationship.updated_at = marker
        s.flush()

        people_index.replace_source_evidence(
            s,
            "toolx",
            "sourcex",
            [{**observation, "verification_status": AUTHOR_CLAIM_UNVERIFIED}],
        )

        assert relationship.verification_status == AUTHOR_CLAIM_UNVERIFIED
        assert relationship.resolved_at > marker
        assert relationship.updated_at > marker


def test_a_person_confirmed_unchanged_is_not_restamped():
    """Re-deriving the same identity must not queue a write on `people`."""
    with db.session_scope() as s:
        person = people_index.ensure_person(
            s,
            display_name="Grace",
            toolhub_user_id="grace-1",
            toolhub_username="Grace",
            source="toolhub_public_account",
        )
        marker = utcnow() - timedelta(days=3)
        person.updated_at = marker
        s.flush()

        people_index.ensure_person(
            s,
            display_name="Grace",
            toolhub_user_id="grace-1",
            toolhub_username="Grace",
            source="toolhub_public_account",
        )

        # A write here sets `updated_at` and nothing else -- the statement the
        # deploy migration waited out its lock timeout on.
        assert person.updated_at == marker


def test_a_person_whose_row_moved_is_restamped():
    with db.session_scope() as s:
        person = people_index.ensure_person(s, display_name="grace hopper", source="wiki")
        marker = utcnow() - timedelta(days=3)
        person.updated_at = marker
        s.flush()

        # The same person by any casing, now written the way its source spells it.
        people_index.ensure_person(s, display_name="Grace Hopper", source="wiki")

        assert person.display_name == "Grace Hopper"
        assert person.updated_at > marker


def _current_identifier(s, namespace: str, value: str) -> PersonIdentifier:
    """Return the one identifier row a namespace/value pair resolves to."""
    return s.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.namespace == namespace,
            PersonIdentifier.normalized_value == value.casefold(),
        )
    ).scalar_one()


def test_reconfirming_an_unchanged_identifier_writes_nothing():
    # The 2026-08-24 deploy waited out its lock timeout on exactly this
    # statement -- `SET last_seen_at=..., updated_at=...` and no data -- against
    # people-reconcile-incremental, which rewrites this table every minute.
    with db.session_scope() as s:
        people_index.ensure_person(
            s,
            display_name="Ada",
            toolhub_user_id="ada-1",
            toolhub_username="Ada",
            source="toolhub_public_account",
        )
        s.flush()
        row = _current_identifier(s, people_index.NS_TOOLHUB_USER_ID, "ada-1")
        marker = utcnow() - timedelta(days=3)
        row.last_seen_at = marker
        row.updated_at = marker
        s.flush()

        people_index.ensure_person(
            s,
            display_name="Ada",
            toolhub_user_id="ada-1",
            toolhub_username="Ada",
            source="toolhub_public_account",
        )

        assert row not in s.dirty
        assert row.last_seen_at == marker
        assert row.updated_at == marker


def test_an_identifier_whose_row_moved_is_restamped():
    # Same identifier, respelled by its source. `normalized_value` is unchanged,
    # so this is the same row -- but `value` moved, and provenance must follow.
    with db.session_scope() as s:
        people_index.ensure_person(
            s,
            display_name="Ada",
            toolhub_user_id="ada-2",
            wiki_username="ada lovelace",
            source="wiki",
        )
        s.flush()
        row = _current_identifier(s, people_index.NS_WIKI_USERNAME, "ada lovelace")
        marker = utcnow() - timedelta(days=3)
        row.last_seen_at = marker
        row.updated_at = marker
        s.flush()

        people_index.ensure_person(
            s,
            display_name="Ada",
            toolhub_user_id="ada-2",
            wiki_username="Ada Lovelace",
            source="wiki",
        )

        assert row.value == "Ada Lovelace"
        assert row.last_seen_at > marker
        assert row.updated_at > marker


def test_a_newly_created_identifier_carries_a_timestamp():
    # A pending row reports as unmodified, so without the created flag the
    # guard would leave every new identifier unstamped.
    with db.session_scope() as s:
        before = utcnow() - timedelta(seconds=1)
        people_index.ensure_person(
            s,
            display_name="Ada",
            toolhub_user_id="ada-3",
            source="toolhub_public_account",
        )
        s.flush()

        row = _current_identifier(s, people_index.NS_TOOLHUB_USER_ID, "ada-3")
        assert row.last_seen_at is not None
        assert row.last_seen_at >= before


def _count_evidence_updates(fn):
    """Run fn(session) and return the UPDATEs it issued against the evidence table.

    Counting statements rather than comparing values is the whole point: the
    values were always correct, and it was the writes that were wasted. A test
    that asserted on the row would have passed throughout the defect.
    """
    from sqlalchemy import event

    emitted = []

    def _record(conn, cursor, statement, parameters, context, many):  # noqa: PLR0913 - SQLAlchemy's signature
        if statement.lstrip().upper().startswith("UPDATE TOOL_RELATIONSHIP_EVIDENCE"):
            emitted.append(statement)

    engine = db.engine()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        with db.session_scope() as session:
            fn(session)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return len(emitted)


def _observe(session, *, confidence=90):
    from backend import people_policy

    return people_index._upsert_relationship_evidence(
        session,
        tool_name="probe-tool",
        person_id=1,
        role=PERSON_REL_MAINTAINER,
        source=SYNC_OFFICIAL,
        method="toolinfo_verified_author_anchor",
        evidence_key="probe-key",
        observation={"display_name": "Ada", "confidence": confidence, "verification_status": AUTHOR_CLAIM_VERIFIED},
        identity_decision=people_policy.IdentityDecision(action="bind", reason="stable-id", confidence=100),
        now=utcnow(),
    )


def test_confirming_an_unchanged_observation_issues_no_update():
    """The write that six jobs contend on, and that nothing needed.

    tool_relationship_evidence is rewritten by people-reconcile-incremental every
    minute and by five other jobs; errno 1205 lock-wait timeouts had failed runs
    179 times by 2026-09-03. Assigning the columns unconditionally took a row
    lock to store what was already there.
    """
    _count_evidence_updates(_observe)  # first pass creates the row

    updates = _count_evidence_updates(_observe)

    assert updates == 0, f"an unchanged observation still issued {updates} UPDATE(s)"


def test_a_changed_observation_still_writes():
    """Suppression must not swallow a real change."""
    _count_evidence_updates(_observe)

    updates = _count_evidence_updates(lambda s: _observe(s, confidence=42))

    assert updates == 1
    with db.session_scope() as session:
        row = session.execute(select(ToolRelationshipEvidence)).scalar_one()
        assert row.confidence == 42
