# SPDX-License-Identifier: GPL-3.0-or-later
"""Acceptance matrix for conservative people reconciliation policy."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import people_policy  # noqa: E402


def test_stable_authenticated_handle_and_review_evidence_can_auto_link():
    cases = [
        ({"same_stable_identifier": True}, people_policy.REASON_STABLE_ID),
        ({"authenticated_claim": True}, people_policy.REASON_AUTHENTICATED),
        ({"operator_approved": True}, people_policy.REASON_REVIEWED),
        ({"structured_handle": True}, people_policy.REASON_STRUCTURED_HANDLE),
    ]
    for evidence, reason in cases:
        decision = people_policy.decide_identity_link(**evidence)
        assert decision.action == people_policy.ACTION_AUTO_LINK
        assert decision.reason == reason


def test_display_matches_are_candidates_never_automatic_links():
    exact = people_policy.decide_identity_link(exact_toolhub_candidate=True)
    corroborated = people_policy.decide_identity_link(
        exact_toolhub_candidate=True,
        same_tool_toolforge_membership=True,
    )
    display_only = people_policy.decide_identity_link()

    assert (exact.action, exact.confidence) == (people_policy.ACTION_CANDIDATE, 70)
    assert (corroborated.action, corroborated.confidence) == (people_policy.ACTION_CANDIDATE, 90)
    assert display_only.action == people_policy.ACTION_UNRESOLVED


def test_conflicting_stable_ids_override_every_merge_signal():
    decision = people_policy.decide_identity_link(
        conflicting_stable_identifiers=True,
        same_stable_identifier=True,
        authenticated_claim=True,
        operator_approved=True,
    )
    assert decision.action == people_policy.ACTION_CONFLICT


def test_relationship_basis_does_not_turn_membership_into_authorship():
    assert people_policy.relationship_basis("author", "toolforge_maintainer") == "toolforge_access_or_maintainership"
    assert people_policy.relationship_basis("author", "toolhub_author_metadata") == "authorship_attribution"
