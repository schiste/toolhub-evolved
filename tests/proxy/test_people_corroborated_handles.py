# SPDX-License-Identifier: GPL-3.0-or-later
"""A bare author label resolves only when an independent edge corroborates it."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, people_policy  # noqa: E402
from backend.models import ToolRelationshipEvidence, UnresolvedAttributionEvidence  # noqa: E402
from backend.sync import AUTHOR_CLAIM_VERIFIED, PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER  # noqa: E402

MAINTAINER_SOURCE = "toolforge_toolsadmin"
CANONICAL_SOURCE = "toolhub_canonical"


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _stable_person(session, display_name, global_id, **handles):
    return people_index.ensure_person(
        session,
        display_name=display_name,
        wikimedia_global_user_id=global_id,
        source="test",
        **handles,
    )


def _verified_maintainer_edge(session, tool, label, source=MAINTAINER_SOURCE):
    """Give the tool an independent, verified maintainer edge to corroborate."""
    people_index.replace_source_evidence(
        session,
        tool,
        source,
        [
            {
                "relationship_type": PERSON_REL_MAINTAINER,
                "method": "toolforge_maintainer",
                "evidence_key": f"{tool}:{label}",
                "display_name": label,
                "wiki_username": label,
                "verification_status": AUTHOR_CLAIM_VERIFIED,
                "confidence": 100,
            }
        ],
    )


def _canonical_author_label(session, tool, label):
    """Record the catalog's free-text author value, which carries no identity."""
    people_index.replace_source_evidence(
        session,
        tool,
        CANONICAL_SOURCE,
        [
            {
                "relationship_type": PERSON_REL_AUTHOR,
                "method": "author_display_name",
                "evidence_key": f"{tool}:author",
                "display_name": label,
            }
        ],
    )


def _author_person_ids(session, tool):
    return {
        row.person_id
        for row in session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == tool,
                ToolRelationshipEvidence.relationship_type == PERSON_REL_AUTHOR,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
        ).scalars()
    }


def _unresolved_labels(session, tool):
    return {
        row.normalized_label
        for row in session.execute(
            select(UnresolvedAttributionEvidence).where(
                UnresolvedAttributionEvidence.tool_name == tool,
                UnresolvedAttributionEvidence.withdrawn_at.is_(None),
            )
        ).scalars()
    }


def test_label_resolves_when_the_person_already_maintains_that_tool():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        _canonical_author_label(session, "toolx", "Ada")

        assert _author_person_ids(session, "toolx") == {ada.id}
        assert _unresolved_labels(session, "toolx") == set()


def test_the_same_label_stays_unresolved_without_a_corroborating_edge():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        # No maintainer edge: the handle matches, but nothing ties Ada to this
        # tool, which is the case a bare name must never be allowed to assert.
        _canonical_author_label(session, "toolx", "Ada")

        assert _author_person_ids(session, "toolx") == set()
        assert _unresolved_labels(session, "toolx") == {"ada"}


def test_an_edge_from_the_same_source_cannot_corroborate_itself():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada", source=CANONICAL_SOURCE)
        _canonical_author_label(session, "toolx", "Ada")

        assert _unresolved_labels(session, "toolx") == {"ada"}


def test_an_unverified_edge_does_not_corroborate():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        people_index.replace_source_evidence(
            session,
            "toolx",
            MAINTAINER_SOURCE,
            [
                {
                    "relationship_type": PERSON_REL_MAINTAINER,
                    "method": "toolforge_maintainer",
                    "evidence_key": "toolx:Ada",
                    "display_name": "Ada",
                    "wiki_username": "Ada",
                    "verification_status": "unverified",
                }
            ],
        )
        _canonical_author_label(session, "toolx", "Ada")

        assert _unresolved_labels(session, "toolx") == {"ada"}


def test_a_label_shared_by_two_people_resolves_nothing():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _stable_person(session, "Ada Two", "43", toolforge_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        _canonical_author_label(session, "toolx", "Ada")

        assert _unresolved_labels(session, "toolx") == {"ada"}


def test_a_handle_known_only_from_an_untrusted_source_resolves_nothing():
    with db.session_scope() as session:
        # A repository scan is not a trusted handle provenance, so this person
        # is not publishable and its handle must not lend identity to a label,
        # even though the corroborating edge itself is present.
        _verified_maintainer_edge(session, "toolx", "Ghost", source="repository_scan")
        _canonical_author_label(session, "toolx", "Ghost")

        assert _unresolved_labels(session, "toolx") == {"ghost"}


def test_matching_is_case_insensitive_like_the_rest_of_the_handle_rules():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        _canonical_author_label(session, "toolx", "aDa")

        assert _author_person_ids(session, "toolx") == {ada.id}


def test_resolution_records_its_reason_for_audit():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        _canonical_author_label(session, "toolx", "Ada")
        row = session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == "toolx",
                ToolRelationshipEvidence.relationship_type == PERSON_REL_AUTHOR,
            )
        ).scalar_one()

        assert row.evidence_payload["identityResolution"]["reason"] == people_policy.REASON_HANDLE_CORROBORATED


def test_corroborated_handles_never_outrank_a_stable_identifier():
    corroborated = people_policy.decide_identity_link(corroborated_handle=True)
    assert corroborated.action == people_policy.ACTION_AUTO_LINK
    assert corroborated.reason == people_policy.REASON_HANDLE_CORROBORATED
    # A stable id and a declared structured handle both still win, and a
    # conflict still refuses everything.
    assert people_policy.decide_identity_link(same_stable_identifier=True, corroborated_handle=True).reason == (
        people_policy.REASON_STABLE_ID
    )
    assert people_policy.decide_identity_link(structured_handle=True, corroborated_handle=True).reason == (
        people_policy.REASON_STRUCTURED_HANDLE
    )
    assert people_policy.decide_identity_link(
        conflicting_stable_identifiers=True, corroborated_handle=True
    ).action == people_policy.ACTION_CONFLICT


def test_a_bare_label_with_no_matching_handle_is_untouched():
    with db.session_scope() as session:
        _canonical_author_label(session, "toolx", "Nobody At All")
        assert _unresolved_labels(session, "toolx") == {"nobody at all"}


PHABRICATOR_SOURCE = "phabricator_profile"


def test_a_phabricator_real_name_resolves_a_label_no_handle_could_reach():
    with db.session_scope() as session:
        # The exact production shape: Toolsadmin renders the LDAP cn as the
        # maintainer handle and the Phabricator real name as the catalog author,
        # so the two never match and the label has always gone unresolved.
        gopa = _stable_person(session, "Gopavasanth", "42", wiki_username="Gopavasanth")
        people_index.record_phabricator_real_name(session, gopa, real_name="Gopa Vasanth", source=PHABRICATOR_SOURCE)
        _verified_maintainer_edge(session, "dabfix", "Gopavasanth")
        _canonical_author_label(session, "dabfix", "Gopa Vasanth")

        assert _author_person_ids(session, "dabfix") == {gopa.id}
        assert _unresolved_labels(session, "dabfix") == set()


def test_a_real_name_still_needs_the_independent_edge():
    with db.session_scope() as session:
        gopa = _stable_person(session, "Gopavasanth", "42", wiki_username="Gopavasanth")
        people_index.record_phabricator_real_name(session, gopa, real_name="Gopa Vasanth", source=PHABRICATOR_SOURCE)
        # No maintainer edge on this tool: a name read off a public profile is
        # an identity fact, never an authorship one.
        _canonical_author_label(session, "someone-elses-tool", "Gopa Vasanth")

        assert _author_person_ids(session, "someone-elses-tool") == set()
        assert _unresolved_labels(session, "someone-elses-tool") == {"gopa vasanth"}


def test_a_real_name_another_person_already_carries_is_refused_not_moved():
    with db.session_scope() as session:
        # policy refuses to offer a shared name at all, so this only happens
        # when two sweeps disagree. The name must not silently change owner.
        one = _stable_person(session, "Adam", "42", wiki_username="adam1")
        two = _stable_person(session, "Adam", "43", wiki_username="adam2")
        assert people_index.record_phabricator_real_name(
            session, one, real_name="Adam Smith", source=PHABRICATOR_SOURCE
        )
        assert (
            people_index.record_phabricator_real_name(session, two, real_name="Adam Smith", source=PHABRICATOR_SOURCE)
            is None
        )

        _verified_maintainer_edge(session, "toolx", "adam2")
        _canonical_author_label(session, "toolx", "Adam Smith")
        # The name still belongs to the first writer, who has no edge here, so
        # the second person's tool gains nothing from the collision.
        assert _author_person_ids(session, "toolx") == set()
        assert _unresolved_labels(session, "toolx") == {"adam smith"}


def test_a_superseded_real_name_stops_matching_once_retired():
    with db.session_scope() as session:
        person = _stable_person(session, "Volans", "42", wiki_username="volans")
        people_index.record_phabricator_real_name(session, person, real_name="Old Name", source=PHABRICATOR_SOURCE)
        people_index.record_phabricator_real_name(session, person, real_name="New Name", source=PHABRICATOR_SOURCE)
        assert people_index.retire_phabricator_real_names(session, person, keep="New Name") == 1
        _verified_maintainer_edge(session, "toolx", "volans")

        _canonical_author_label(session, "toolx", "Old Name")
        assert _unresolved_labels(session, "toolx") == {"old name"}
        _canonical_author_label(session, "toolx", "New Name")
        assert _author_person_ids(session, "toolx") == {person.id}


def test_a_real_name_is_not_published_as_a_handle():
    with db.session_scope() as session:
        person = _stable_person(session, "Gopavasanth", "42", wiki_username="Gopavasanth")
        people_index.record_phabricator_real_name(session, person, real_name="Gopa Vasanth", source=PHABRICATOR_SOURCE)

        assert people_index.NS_PHABRICATOR_REAL_NAME not in people_index.PUBLIC_HANDLE_NAMESPACES
