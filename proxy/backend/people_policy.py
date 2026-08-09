# SPDX-License-Identifier: GPL-3.0-or-later
"""Central policy for identity linking and relationship attribution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

ACTION_AUTO_LINK = "auto_link"
ACTION_CANDIDATE = "candidate"
ACTION_UNRESOLVED = "unresolved"
ACTION_CONFLICT = "conflict"

REASON_STABLE_ID = "same_stable_identifier"
REASON_STRUCTURED_HANDLE = "same_verified_structured_handle"
REASON_AUTHENTICATED = "authenticated_account_claim"
REASON_REVIEWED = "operator_approved_mapping"
REASON_EXACT_TOOLHUB = "exact_toolhub_username_candidate"
REASON_TOOLFORGE_CORROBORATED = "exact_toolhub_username_and_toolforge_membership"
REASON_SUL_TOOLFORGE_MEMBERSHIP = "wikimedia_identity_and_toolforge_sul_membership"
REASON_DISPLAY_ONLY = "display_name_only"
REASON_STABLE_CONFLICT = "conflicting_stable_identifiers"

VIEWER_AUDIENCE_CONTRIBUTOR = "contributor"
VIEWER_AUDIENCE_MAINTAINER = "verified_maintainer"
VIEWER_AUDIENCE_RECORD_AUTHORITY = "record_authority"


@dataclass(frozen=True)
class IdentityDecision:
    """One deterministic policy outcome with an operator-readable reason."""

    action: str
    reason: str
    confidence: int


def decide_identity_link(  # noqa: PLR0911, PLR0913 - explicit flags document precedence
    *,
    same_stable_identifier: bool = False,
    structured_handle: bool = False,
    authenticated_claim: bool = False,
    operator_approved: bool = False,
    exact_toolhub_candidate: bool = False,
    same_tool_toolforge_membership: bool = False,
    toolforge_sul_bound: bool = False,
    conflicting_stable_identifiers: bool = False,
) -> IdentityDecision:
    """Return the only allowed identity action for a set of evidence facts."""
    if conflicting_stable_identifiers:
        return IdentityDecision(ACTION_CONFLICT, REASON_STABLE_CONFLICT, 100)
    if same_stable_identifier:
        return IdentityDecision(ACTION_AUTO_LINK, REASON_STABLE_ID, 100)
    if authenticated_claim:
        return IdentityDecision(ACTION_AUTO_LINK, REASON_AUTHENTICATED, 100)
    if operator_approved:
        return IdentityDecision(ACTION_AUTO_LINK, REASON_REVIEWED, 100)
    if structured_handle:
        return IdentityDecision(ACTION_AUTO_LINK, REASON_STRUCTURED_HANDLE, 90)
    if exact_toolhub_candidate and toolforge_sul_bound and same_tool_toolforge_membership:
        return IdentityDecision(ACTION_AUTO_LINK, REASON_SUL_TOOLFORGE_MEMBERSHIP, 95)
    if exact_toolhub_candidate and same_tool_toolforge_membership:
        return IdentityDecision(ACTION_CANDIDATE, REASON_TOOLFORGE_CORROBORATED, 90)
    if exact_toolhub_candidate:
        return IdentityDecision(ACTION_CANDIDATE, REASON_EXACT_TOOLHUB, 70)
    return IdentityDecision(ACTION_UNRESOLVED, REASON_DISPLAY_ONLY, 0)


def relationship_basis(role: str, method: str) -> str:
    """Describe what a source proves without upgrading one role into another."""
    if method == "toolforge_maintainer":
        return "toolforge_access_or_maintainership"
    if method in {"signed_toolinfo", "toolinfo_url_control"}:
        return "maintainer_control"
    if method == "toolhub_write_access":
        return "toolhub_record_authority"
    if role == "author":
        return "authorship_attribution"
    if role == "catalog_actor":
        return "catalog_activity"
    return "relationship_observation"


def viewer_action_audience(
    relationships: Iterable[Mapping[str, Any]],
    *,
    checked_at: datetime,
) -> str:
    """Classify action wording from current verified per-tool relationships."""
    current_roles = {
        str(row.get("type") or "")
        for row in relationships
        if row.get("status") == "verified" and (row.get("expires_at") is None or row["expires_at"] > checked_at)
    }
    if "record_owner" in current_roles:
        return VIEWER_AUDIENCE_RECORD_AUTHORITY
    if "maintainer" in current_roles:
        return VIEWER_AUDIENCE_MAINTAINER
    return VIEWER_AUDIENCE_CONTRIBUTOR
