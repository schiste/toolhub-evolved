# SPDX-License-Identifier: GPL-3.0-or-later
"""A bare author label resolves only when an independent edge corroborates it."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, people_policy, people_reconcile  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCacheMeta,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    ToolSummaryCache,
    UnresolvedAttributionEvidence,
    utcnow,
)
from backend.sync import (  # noqa: E402
    AUTHOR_CLAIM_UNVERIFIED,
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
)

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


def _maintainer_person_ids(session, tool):
    return {
        row.person_id
        for row in session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == tool,
                ToolRelationshipEvidence.relationship_type == PERSON_REL_MAINTAINER,
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


def test_a_label_two_holders_of_the_same_tool_share_resolves_nothing():
    with db.session_scope() as session:
        # Both carry the handle and both are proven on this tool, so the tool's
        # own evidence cannot say which of them the label names.
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        two = _stable_person(session, "Ada Two", "43", toolforge_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        # Reach the second person by the handle namespace only she holds, so
        # both really are proven on this tool rather than one being resolved
        # twice under the same name.
        people_index.replace_source_evidence(
            session,
            "toolx",
            "toolhub_maintainers",
            [
                {
                    "relationship_type": PERSON_REL_MAINTAINER,
                    "method": "toolhub_maintainer",
                    "evidence_key": "toolx:AdaTwo",
                    "display_name": "Ada",
                    "toolforge_username": "Ada",
                    "verification_status": AUTHOR_CLAIM_VERIFIED,
                    "confidence": 100,
                }
            ],
        )
        assert two.id in _maintainer_person_ids(session, "toolx")
        _canonical_author_label(session, "toolx", "Ada")

        assert _unresolved_labels(session, "toolx") == {"ada"}


def test_a_label_shared_elsewhere_resolves_to_the_holder_of_this_tool():
    with db.session_scope() as session:
        # A stranger sharing the handle used to veto this, even though nothing
        # ties them to the tool. Holding the tool is the evidence; carrying the
        # same name somewhere else in the catalog is not counter-evidence.
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        _stable_person(session, "Ada Two", "43", toolforge_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        _canonical_author_label(session, "toolx", "Ada")

        assert _author_person_ids(session, "toolx") == {ada.id}
        assert _unresolved_labels(session, "toolx") == set()


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


def test_a_spaced_label_matches_the_unspaced_handle_of_the_same_person():
    with db.session_scope() as session:
        # The largest real cluster: 67 tools credit "Bryan Davis" while every
        # handle the account carries reads "BryanDavis".
        bryan = _stable_person(session, "BryanDavis", "42", wiki_username="BryanDavis")
        _verified_maintainer_edge(session, "toolx", "BryanDavis")
        _canonical_author_label(session, "toolx", "Bryan Davis")

        assert _author_person_ids(session, "toolx") == {bryan.id}
        assert _unresolved_labels(session, "toolx") == set()


@pytest.mark.parametrize(
    ("handle", "label"),
    [
        ("lokal-profil", "Lokal_Profil"),  # LDAP hyphen against the wiki underscore
        ("TheresNoTime", "There'sNoTime"),  # an apostrophe the catalog keeps
        ("Ada", "  Ada  "),  # surrounding whitespace
    ],
)
def test_separator_spellings_of_one_name_all_match(handle, label):
    with db.session_scope() as session:
        person = _stable_person(session, handle, "42", wiki_username=handle)
        _verified_maintainer_edge(session, "toolx", handle)
        _canonical_author_label(session, "toolx", label)

        assert _author_person_ids(session, "toolx") == {person.id}


def test_names_differing_by_more_than_separators_still_do_not_match():
    with db.session_scope() as session:
        # Folding separators must not fold letters or digits: these are two
        # different names, and dropping the punctuation does not make them one.
        _stable_person(session, "Ada Lovelace", "42", wiki_username="AdaLovelace")
        _verified_maintainer_edge(session, "toolx", "AdaLovelace")
        _canonical_author_label(session, "toolx", "Ada Lovelace2")

        assert _author_person_ids(session, "toolx") == set()
        assert _unresolved_labels(session, "toolx") == {"ada lovelace2"}


def test_a_label_of_only_separators_resolves_nothing():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        # Squashing this to an empty key must refuse, not match every handle.
        assert (
            people_index.corroborated_handle_person(
                session, tool_name="toolx", display_name=" - _ . ", source=CANONICAL_SOURCE
            )
            is None
        )


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


def _relationship_status(session, tool, person_id, role=PERSON_REL_AUTHOR):
    row = session.execute(
        select(ToolPersonRelationship).where(
            ToolPersonRelationship.tool_name == tool,
            ToolPersonRelationship.person_id == person_id,
            ToolPersonRelationship.relationship_type == role,
        )
    ).scalar_one_or_none()
    return None if row is None else row.verification_status


def test_a_label_ingested_before_its_corroborating_edge_stays_unresolved():
    # The gap reconvergence exists to close. Corroboration is the one rule whose
    # answer can change without its own observation changing, and ingest judges
    # each observation once, so this row's verdict is decided by feed order.
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")

        assert _unresolved_labels(session, "toolx") == {"ada"}
        assert _author_person_ids(session, "toolx") == set()


def test_reconvergence_promotes_a_label_its_own_feed_would_not_revisit():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")

        assert people_reconcile.reconverge_attributions(session) == {
            "examined": 1,
            "promoted": 1,
            "tools": 1,
        }
        assert _author_person_ids(session, "toolx") == {ada.id}
        assert _unresolved_labels(session, "toolx") == set()
        # Promotion is not complete until the collapsed relationship exists:
        # that row is what the catalog reads. It carries the observation's own
        # strength, not the corroborating edge's -- corroboration decided who
        # this label names, which is identification, and left how well the
        # authorship itself is attested exactly where the source left it.
        assert _relationship_status(session, "toolx", ada.id) == AUTHOR_CLAIM_UNVERIFIED
        assert _relationship_status(session, "toolx", ada.id, PERSON_REL_MAINTAINER) == AUTHOR_CLAIM_VERIFIED


def test_reconvergence_records_the_same_reason_as_ingest_time_corroboration():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        people_reconcile.reconverge_attributions(session)
        row = session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == "toolx",
                ToolRelationshipEvidence.relationship_type == PERSON_REL_AUTHOR,
            )
        ).scalar_one()

        assert row.evidence_payload["identityResolution"]["reason"] == people_policy.REASON_HANDLE_CORROBORATED
        assert row.verification_status == AUTHOR_CLAIM_UNVERIFIED
        assert row.observed_name == "Ada"


def test_reconvergence_leaves_a_label_nothing_corroborates():
    # It re-decides rows under the same rule, so a row the rule refuses stays
    # refused. Nothing here loosens what may be linked.
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toolx", "Ada")

        assert people_reconcile.reconverge_attributions(session) == {
            "examined": 0,
            "promoted": 0,
            "tools": 0,
        }
        assert _unresolved_labels(session, "toolx") == {"ada"}


def test_reconvergence_refuses_a_label_two_holders_of_the_tool_share():
    with db.session_scope() as session:
        _stable_person(session, "Ada L", "42", wiki_username="Ada")
        _stable_person(session, "Ada B", "43", toolhub_username="A-d-a")
        _canonical_author_label(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "A-d-a", source="toolinfo_source_attestation")

        # Read, because the tool now has verified edges, and still refused.
        assert people_reconcile.reconverge_attributions(session) == {
            "examined": 1,
            "promoted": 0,
            "tools": 0,
        }
        assert _unresolved_labels(session, "toolx") == {"ada"}


def test_reconvergence_walks_a_cursor_so_a_bounded_batch_still_covers_everything():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        for tool in ("toola", "toolb"):
            _canonical_author_label(session, tool, "Ada")
            _verified_maintainer_edge(session, tool, "Ada")

        first = people_reconcile.reconverge_attributions(session, limit=1)
        assert first == {"examined": 1, "promoted": 1, "tools": 1}
        assert _author_person_ids(session, "toola") == {ada.id}
        assert _author_person_ids(session, "toolb") == set()

        # The next pass resumes past the row it already decided instead of
        # re-reading the head, which is what makes coverage complete.
        second = people_reconcile.reconverge_attributions(session, limit=1)
        assert second == {"examined": 1, "promoted": 1, "tools": 1}
        assert _author_person_ids(session, "toolb") == {ada.id}


def test_the_cursor_wraps_at_the_tail_so_no_row_starves_behind_a_refused_one():
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        # An eligible row the rule refuses: the tool has verified edges, but the
        # label matches nobody who holds it. It is read on every pass forever.
        _stable_person(session, "Bo", "43", wiki_username="Bo")
        _verified_maintainer_edge(session, "toola", "Bo")
        _canonical_author_label(session, "toola", "Ada")

        assert people_reconcile.reconverge_attributions(session, limit=1) == {
            "examined": 1,
            "promoted": 0,
            "tools": 0,
        }
        # The cursor advanced past it, so the next pass reaches the row behind
        # it rather than re-reading the same refusal forever.
        _canonical_author_label(session, "toolb", "Ada")
        _verified_maintainer_edge(session, "toolb", "Ada")
        assert people_reconcile.reconverge_attributions(session, limit=1) == {
            "examined": 1,
            "promoted": 1,
            "tools": 1,
        }
        assert _author_person_ids(session, "toolb") == {ada.id}

        # Reaching the tail resets the cursor, so the refused head row is
        # revisited on a later pass. Without the wrap it would be decided once
        # and then never re-examined, which is the very failure this pass exists
        # to fix.
        assert people_reconcile.reconverge_attributions(session, limit=1) == {
            "examined": 0,
            "promoted": 0,
            "tools": 0,
        }
        assert people_reconcile.reconverge_attributions(session, limit=1) == {
            "examined": 1,
            "promoted": 0,
            "tools": 0,
        }


def test_reconvergence_ignores_an_expired_observation():
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        row = session.execute(
            select(UnresolvedAttributionEvidence).where(UnresolvedAttributionEvidence.tool_name == "toolx")
        ).scalar_one()
        row.expires_at = utcnow() - timedelta(days=1)
        session.flush()

        # An observation whose source no longer stands by it must not be
        # promoted on the strength of an edge that arrived after it lapsed.
        assert people_reconcile.reconverge_attributions(session) == {
            "examined": 0,
            "promoted": 0,
            "tools": 0,
        }
        assert _author_person_ids(session, "toolx") == set()


def test_a_cursor_stored_as_something_other_than_a_number_starts_from_the_head():
    # The cursor is persisted state, so a migration or a hand edit can leave it
    # unreadable. Refusing to read it has to mean starting the pass over, not
    # raising -- the pass runs unattended, and one bad row must not cost every
    # subsequent hour's crediting.
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        session.add(ApiCacheMeta(key=people_reconcile.RECONVERGE_CURSOR_KEY, value="not-a-number"))
        session.flush()

        assert people_reconcile.reconverge_attributions(session) == {
            "examined": 1,
            "promoted": 1,
            "tools": 1,
        }
        assert _author_person_ids(session, "toolx") == {ada.id}


def test_reconvergence_drops_the_cached_summary_of_a_tool_it_recredited():
    # The summary cache is what the public tool card reads. A promotion that
    # left it standing would credit the person in the database and nowhere a
    # visitor can see, until the cache happened to expire on its own.
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toolx", "Ada")
        _verified_maintainer_edge(session, "toolx", "Ada")
        now = utcnow()
        session.add(
            ToolSummaryCache(
                tool_name="toolx",
                summary={"people": []},
                expires_at=now + timedelta(hours=1),
                stale_until=now + timedelta(hours=2),
            )
        )
        session.flush()

        assert people_reconcile.reconverge_attributions(session)["promoted"] == 1
        assert _author_person_ids(session, "toolx") == {ada.id}
        session.flush()
        assert session.execute(select(ToolSummaryCache)).scalars().all() == []


def test_a_chunked_pass_covers_the_same_backlog_as_one_transaction():
    # Chunking exists to move the commit boundary, not to change the answer.
    # Whatever a single transaction over the batch would have decided, the same
    # rows decided one chunk at a time must decide identically.
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        for tool in ("toola", "toolb", "toolc"):
            _canonical_author_label(session, tool, "Ada")
            _verified_maintainer_edge(session, tool, "Ada")

    assert people_reconcile.reconverge_in_chunks(limit=10, chunk=1) == {
        "examined": 3,
        "promoted": 3,
        "tools": 3,
    }
    with db.session_scope() as session:
        for tool in ("toola", "toolb", "toolc"):
            assert _author_person_ids(session, tool) == {ada.id}


def test_a_chunk_boundary_is_a_commit_so_earlier_work_survives_a_later_failure(monkeypatch):
    # The whole point of the chunk boundary: the locks a chunk took are released
    # there. A pass that kept them to the end could not survive its own failure
    # either, so proving the first chunk's promotion is durable proves the locks
    # behind it are gone.
    with db.session_scope() as session:
        ada = _stable_person(session, "Ada", "42", wiki_username="Ada")
        for tool in ("toola", "toolb"):
            _canonical_author_label(session, tool, "Ada")
            _verified_maintainer_edge(session, tool, "Ada")

    real = people_reconcile._reconverge_batch  # noqa: SLF001 - the boundary under test
    calls = []

    def fail_on_the_second(session, *, batch_size):
        calls.append(batch_size)
        if len(calls) > 1:
            raise RuntimeError("chunk two died")
        return real(session, batch_size=batch_size)

    monkeypatch.setattr(people_reconcile, "_reconverge_batch", fail_on_the_second)
    with pytest.raises(RuntimeError):
        people_reconcile.reconverge_in_chunks(limit=10, chunk=1)

    with db.session_scope() as session:
        assert _author_person_ids(session, "toola") == {ada.id}
        assert _author_person_ids(session, "toolb") == set()


def test_a_chunked_pass_stops_at_the_tail_instead_of_re_reading_the_head():
    # `_reconverge_batch` resets the cursor to the head on a short batch, so a
    # loop that did not stop there would spin over the same rows until it hit
    # its ceiling -- examining far more rows than the backlog holds.
    with db.session_scope() as session:
        _stable_person(session, "Ada", "42", wiki_username="Ada")
        _canonical_author_label(session, "toola", "Ada")
        _verified_maintainer_edge(session, "toola", "Ada")

    assert people_reconcile.reconverge_in_chunks(limit=500, chunk=25)["examined"] == 1
