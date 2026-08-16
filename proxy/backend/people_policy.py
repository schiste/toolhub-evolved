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
MAPPING_APPROVED = "approved"
APPLIED_IDENTITY_MAPPING_DECISIONS = frozenset({ACTION_AUTO_LINK, MAPPING_APPROVED})

# A MediaWiki username is at most 85 bytes and cannot contain these, so a
# label carrying one is not a username no matter what else it looks like.
MAX_USERNAME_LENGTH = 85
MIN_HANDLE_LENGTH = 2
ILLEGAL_USERNAME_CHARACTERS = frozenset("#<>[]|{}/@:")
# Tokens that only appear in prose, never inside a username someone chose.
PROSE_TOKENS = frozenset(
    {"a", "an", "and", "at", "by", "for", "from", "in", "of", "or", "the", "to", "with", "et", "al", "user", "users"}
)
# Non-alphabetic characters a person puts in a handle but not in their name.
HANDLE_SYMBOLS = frozenset("_-~.+*!?^$0123456789")


def is_handle_shaped(label: str) -> bool:
    """Return True when a label is safe to resolve against a public registry.

    Free-text author values mix two populations. Handles are self-chosen and
    high-entropy (``0xDeadbeef``, ``1234qwer1234qwer4``, ``-jem-``); human
    names are low-entropy and collide (``Aaron Liu`` matches a real account
    belonging to someone with no connection to the tool). Resolving the first
    kind is nearly free of risk; resolving the second attaches a real, named
    person to software they may not have written.

    So this fails closed, and the asymmetry is deliberate: a rejected handle
    costs one unresolved label, while a wrongly accepted name misattributes a
    real individual. Multi-word purely alphabetic labels are refused even
    though MediaWiki allows spaces in usernames, because at that point a real
    username and a real name are genuinely indistinguishable.
    """
    text = " ".join(str(label or "").split())
    if not MIN_HANDLE_LENGTH <= len(text) <= MAX_USERNAME_LENGTH:
        return False
    if ILLEGAL_USERNAME_CHARACTERS & set(text):
        return False
    tokens = text.split(" ")
    if any(token.casefold().strip(".,;") in PROSE_TOKENS for token in tokens):
        return False
    if len(tokens) == 1:
        # Single-token labels are overwhelmingly handles here: someone writing
        # their real name almost always writes more than one word.
        return True
    # Several words only look like a handle when something in them is not
    # name-like, such as a digit or a symbol nobody puts in their own name.
    return bool(HANDLE_SYMBOLS & set(text))


REASON_STABLE_ID = "same_stable_identifier"
REASON_STRUCTURED_HANDLE = "same_verified_structured_handle"
REASON_AUTHENTICATED = "authenticated_account_claim"
REASON_REVIEWED = "operator_approved_mapping"
REASON_EXACT_TOOLHUB = "exact_toolhub_username_candidate"
REASON_TOOLFORGE_CORROBORATED = "exact_toolhub_username_and_toolforge_membership"
REASON_SUL_TOOLFORGE_MEMBERSHIP = "wikimedia_identity_and_toolforge_sul_membership"
REASON_HANDLE_CORROBORATED = "verified_handle_and_independent_tool_edge"
REASON_REGISTRY_HANDLE = "public_registry_handle_candidate"
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


def decide_identity_link(  # noqa: C901, PLR0911, PLR0913 - the ordered branches are the trust policy
    *,
    same_stable_identifier: bool = False,
    structured_handle: bool = False,
    authenticated_claim: bool = False,
    operator_approved: bool = False,
    corroborated_handle: bool = False,
    exact_toolhub_candidate: bool = False,
    registry_handle: bool = False,
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
    # A label that is a current verified handle of exactly one publishable
    # person, on a tool that person is already independently tied to. The
    # handle is inferred rather than declared, so it ranks below a structured
    # field, but the independent edge is what carries it: neither the label
    # nor the edge alone links anything.
    if corroborated_handle:
        return IdentityDecision(ACTION_AUTO_LINK, REASON_HANDLE_CORROBORATED, 90)
    if exact_toolhub_candidate and toolforge_sul_bound and same_tool_toolforge_membership:
        return IdentityDecision(ACTION_AUTO_LINK, REASON_SUL_TOOLFORGE_MEMBERSHIP, 95)
    if exact_toolhub_candidate and same_tool_toolforge_membership:
        return IdentityDecision(ACTION_CANDIDATE, REASON_TOOLFORGE_CORROBORATED, 90)
    if exact_toolhub_candidate:
        return IdentityDecision(ACTION_CANDIDATE, REASON_EXACT_TOOLHUB, 70)
    # A public registry confirmed the label names a real account. That is an
    # existence proof, not an authorship one: anyone can type any name into a
    # catalog field. It therefore never links on its own -- it becomes a
    # durable candidate, and only corroboration above promotes it.
    if registry_handle:
        return IdentityDecision(ACTION_CANDIDATE, REASON_REGISTRY_HANDLE, 60)
    return IdentityDecision(ACTION_UNRESOLVED, REASON_DISPLAY_ONLY, 0)


# The Unix login is deliberately absent. It is a lowercased, truncated shell
# handle that often reads as a common first name, so building a profile URL
# from it is the one candidate likely to land on an unrelated Phabricator
# account. The two identity-bearing handles are asked about instead.
PHABRICATOR_HANDLE_KINDS = frozenset({"developer_username", "wikimedia_global_name"})


def accept_phabricator_real_name(  # noqa: PLR0913 - each fact is an independent gate
    *,
    handle_kind: str = "",
    real_name: str = "",
    matched_username: str = "",
    account_count_for_real_name: int = 0,
    conflicting_handle_owner: bool = False,
    account_disabled: bool = False,  # noqa: ARG001 - see the note on departed accounts below
) -> bool:
    """Decide whether one Phabricator real name may identify one account.

    Toolsadmin writes this value into the catalog's ``author`` field, so it is
    the only bridge between a name-shaped label and a handle this project
    holds. It is also the weakest kind of key: unlike a handle, nobody chose
    it to be unique, and two unrelated developers may share one.

    The real name is never resolved on its own -- ``corroborated_handle_person``
    still demands an independent verified edge to the same tool before any
    relationship is written. This gate decides only whether the pair is clean
    enough to record as an identifier at all.

    Four rules, each failing closed:

    A shared real name is refused outright. Downstream corroboration would
    often disambiguate it, but "often" is the wrong bar for a key that names a
    real individual, and the cost of the refusal is one label left unresolved.

    Only an identity-bearing handle may be asked about, for the reason on
    ``PHABRICATOR_HANDLE_KINDS`` above.

    A real name that is merely the handle again is refused, because it adds no
    matching key that the handle namespaces do not already carry. This is
    equality after case folding only, not after collapsing separators: the
    whole population this feature exists for is ``Gopavasanth`` publishing as
    ``Gopa Vasanth``, and a separator-insensitive test would reject exactly
    the labels it is meant to resolve.

    A disabled account is *kept*. Someone who has left Wikimedia still wrote
    the tools they wrote, and dropping them would quietly erase authorship
    history rather than protect anybody.
    """
    name = " ".join(str(real_name or "").split())
    username = " ".join(str(matched_username or "").split())
    if not name or not username or handle_kind not in PHABRICATOR_HANDLE_KINDS:
        return False
    if account_count_for_real_name != 1 or conflicting_handle_owner:
        return False
    return name.casefold() != username.casefold()


def relationship_basis(role: str, method: str) -> str:
    """Describe what a source proves without upgrading one role into another."""
    method_basis = {
        "toolforge_maintainer": "toolforge_access_or_maintainership",
        "toolinfo_target_ldap_membership": "toolforge_access_or_maintainership",
        "toolinfo_source_controller": "source_attested_authorship",
        "toolinfo_verified_author_anchor": "source_attested_authorship",
        "wikimedia_user_space_toolforge_identity": "wikimedia_user_space_attested_authorship",
        "signed_toolinfo": "maintainer_control",
        "toolinfo_url_control": "maintainer_control",
        "toolhub_write_access": "toolhub_record_authority",
    }
    if basis := method_basis.get(method):
        return basis
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
