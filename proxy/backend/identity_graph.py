# SPDX-License-Identifier: GPL-3.0-or-later
"""Central account-to-person binding and identity hydration service."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from backend import people_index
from backend.models import (
    Person,
    PersonAccountBinding,
    PersonIdentifier,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolhubAccountProjection,
    ToolRelationshipEvidence,
    User,
    utcnow,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

PROVIDER_TOOLHUB = "toolhub"
PROVIDER_WIKIMEDIA = "wikimedia"
PROVIDER_TOOLFORGE = "toolforge"

STATUS_VERIFIED = "verified"
STATUS_CANDIDATE = "candidate"
STATUS_CONFLICT = "conflict"
STATUS_REVOKED = "revoked"

PROOF_TOOLHUB_ACCOUNT = "official_toolhub_account"
PROOF_TOOLHUB_WIKIMEDIA = "toolhub_wikimedia_global_id"
PROOF_TOOLFORGE_SUL = "toolforge_ldap_wikimedia_global_id"
PROOF_EXACT_HANDLE = "exact_cross_provider_handle_candidate"
PROOF_AUTHENTICATED = "authenticated_account_control"
PROOF_OPERATOR = "operator_approved"
SOURCE_TOOLFORGE_LDAP = "toolforge_ldap"


class IdentityBindingConflictError(RuntimeError):
    """Raised when a requested binding contradicts an existing stable identity."""


def _binding_conflict(message: str) -> IdentityBindingConflictError:
    return IdentityBindingConflictError(message)


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - projection values are external
    return str(value or "").strip()[:limit]


def person_for_identifier(session: Session, namespace: str, value: str) -> Person | None:
    """Resolve one current external identifier without matching display names."""
    normalized = _clean(value).casefold()
    if not normalized:
        return None
    identifier = session.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.namespace == namespace,
            PersonIdentifier.normalized_value == normalized,
            PersonIdentifier.is_current.is_(True),
        )
    ).scalar_one_or_none()
    return session.get(Person, identifier.person_id) if identifier is not None else None


def _binding(session: Session, provider: str, external_id: str) -> PersonAccountBinding:
    row = session.execute(
        select(PersonAccountBinding).where(
            PersonAccountBinding.provider == provider,
            PersonAccountBinding.external_id == external_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = PersonAccountBinding(provider=provider, external_id=external_id)
        session.add(row)
    return row


def _set_binding(  # noqa: PLR0913 - audited proof fields are intentionally explicit
    session: Session,
    *,
    provider: str,
    external_id: str,
    person_id: int | None,
    status: str,
    proof_method: str,
    confidence: int,
    evidence: dict[str, Any],
    verified_by_user_id: int | None = None,
) -> PersonAccountBinding:
    row = _binding(session, provider, external_id)
    if row.status == STATUS_VERIFIED and row.person_id != person_id and status != STATUS_CONFLICT:
        message = f"{provider} account {external_id} is already verified for another person"
        raise _binding_conflict(message)
    now = utcnow()
    row.person_id = person_id
    row.status = status
    row.proof_method = proof_method
    row.confidence = max(0, min(100, confidence))
    row.evidence = evidence
    row.verified_by_user_id = verified_by_user_id
    row.verified_at = now if status == STATUS_VERIFIED else None
    row.revoked_at = None
    row.last_seen_at = now
    row.updated_at = now
    session.flush()
    return row


def _stable_owner_conflict(session: Session, person: Person, uid_number: str) -> bool:
    owner = person_for_identifier(session, people_index.NS_TOOLFORGE_UID_NUMBER, uid_number)
    return owner is not None and owner.id != person.id


def bind_toolforge_account(  # noqa: PLR0913 - proof metadata is part of the security boundary
    session: Session,
    *,
    account: ToolforgeAccountProjection,
    person: Person,
    proof_method: str,
    confidence: int,
    evidence: dict[str, Any],
    verified_by_user_id: int | None = None,
) -> PersonAccountBinding:
    """Verify one immutable Toolforge account and attach its identifiers."""
    if _stable_owner_conflict(session, person, account.uid_number):
        message = f"Toolforge uidNumber {account.uid_number} belongs to another person"
        raise _binding_conflict(message)
    if not people_index.attach_verified_external_account(
        session,
        person,
        stable_namespace=people_index.NS_TOOLFORGE_UID_NUMBER,
        stable_id=account.uid_number,
        handle_namespace=people_index.NS_TOOLFORGE_USERNAME,
        handle=account.uid,
        source=proof_method,
    ):
        message = f"Toolforge uidNumber {account.uid_number} could not be attached"
        raise _binding_conflict(message)
    return _set_binding(
        session,
        provider=PROVIDER_TOOLFORGE,
        external_id=account.uid_number,
        person_id=person.id,
        status=STATUS_VERIFIED,
        proof_method=proof_method,
        confidence=confidence,
        evidence=evidence,
        verified_by_user_id=verified_by_user_id,
    )


def _sync_toolhub_bindings(session: Session) -> int:
    touched = 0
    accounts = list(session.execute(select(ToolhubAccountProjection)).scalars())
    for account in accounts:
        person = people_index.ensure_official_account_person(
            session,
            toolhub_user_id=account.toolhub_user_id,
            username=account.username,
            wikimedia_global_user_id=account.wikimedia_global_user_id or "",
            checked_at=account.last_seen_at,
        )
        if person is None:
            continue
        _set_binding(
            session,
            provider=PROVIDER_TOOLHUB,
            external_id=account.toolhub_user_id,
            person_id=person.id,
            status=STATUS_VERIFIED,
            proof_method=PROOF_TOOLHUB_ACCOUNT,
            confidence=100,
            evidence={"toolhubUserId": account.toolhub_user_id},
        )
        touched += 1
        if account.wikimedia_global_user_id:
            _set_binding(
                session,
                provider=PROVIDER_WIKIMEDIA,
                external_id=account.wikimedia_global_user_id,
                person_id=person.id,
                status=STATUS_VERIFIED,
                proof_method=PROOF_TOOLHUB_WIKIMEDIA,
                confidence=100,
                evidence={
                    "toolhubUserId": account.toolhub_user_id,
                    "wikimediaGlobalUserId": account.wikimedia_global_user_id,
                },
            )
            touched += 1
    return touched


def _unique_toolhub_handle_candidate(
    session: Session, account: ToolforgeAccountProjection
) -> tuple[ToolhubAccountProjection, Person] | None:
    matches = list(
        session.execute(
            select(ToolhubAccountProjection).where(
                ToolhubAccountProjection.normalized_username == account.normalized_uid
            )
        ).scalars()
    )
    if len(matches) != 1:
        return None
    toolhub_account = matches[0]
    person = person_for_identifier(session, people_index.NS_TOOLHUB_USER_ID, toolhub_account.toolhub_user_id)
    return (toolhub_account, person) if person is not None else None


def _sync_toolforge_bindings(session: Session) -> dict[str, int]:
    accounts = list(session.execute(select(ToolforgeAccountProjection)).scalars())
    global_counts = Counter(
        account.wikimedia_global_user_id for account in accounts if account.wikimedia_global_user_id
    )
    stats = {"verified": 0, "candidate": 0, "conflict": 0, "unresolved": 0}
    for account in accounts:
        global_id = account.wikimedia_global_user_id or ""
        if global_id and global_counts[global_id] > 1:
            _set_binding(
                session,
                provider=PROVIDER_TOOLFORGE,
                external_id=account.uid_number,
                person_id=None,
                status=STATUS_CONFLICT,
                proof_method=PROOF_TOOLFORGE_SUL,
                confidence=100,
                evidence={"wikimediaGlobalUserId": global_id, "reason": "duplicate_global_id"},
            )
            stats["conflict"] += 1
            continue
        if global_id:
            person = person_for_identifier(session, people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, global_id)
            if person is None:
                person = people_index.ensure_person(
                    session,
                    display_name=account.wikimedia_global_name or account.uid,
                    wikimedia_global_user_id=global_id,
                    wiki_username=account.wikimedia_global_name,
                    source=PROOF_TOOLFORGE_SUL,
                )
            try:
                bind_toolforge_account(
                    session,
                    account=account,
                    person=person,
                    proof_method=PROOF_TOOLFORGE_SUL,
                    confidence=100,
                    evidence={
                        "wikimediaGlobalUserId": global_id,
                        "toolforgeUidNumber": account.uid_number,
                    },
                )
            except IdentityBindingConflictError:
                _set_binding(
                    session,
                    provider=PROVIDER_TOOLFORGE,
                    external_id=account.uid_number,
                    person_id=None,
                    status=STATUS_CONFLICT,
                    proof_method=PROOF_TOOLFORGE_SUL,
                    confidence=100,
                    evidence={"wikimediaGlobalUserId": global_id, "reason": "stable_identifier_conflict"},
                )
                stats["conflict"] += 1
            else:
                stats["verified"] += 1
            continue
        candidate = _unique_toolhub_handle_candidate(session, account)
        if candidate is None:
            stats["unresolved"] += 1
            continue
        toolhub_account, person = candidate
        existing = _binding(session, PROVIDER_TOOLFORGE, account.uid_number)
        if existing.status == STATUS_VERIFIED:
            stats["verified"] += 1
            continue
        _set_binding(
            session,
            provider=PROVIDER_TOOLFORGE,
            external_id=account.uid_number,
            person_id=person.id,
            status=STATUS_CANDIDATE,
            proof_method=PROOF_EXACT_HANDLE,
            confidence=70,
            evidence={
                "toolforgeUid": account.uid,
                "toolforgeUidNumber": account.uid_number,
                "toolhubUserId": toolhub_account.toolhub_user_id,
                "toolhubUsername": toolhub_account.username,
            },
        )
        stats["candidate"] += 1
    return stats


def _hydrate_local_users(session: Session) -> int:
    touched = 0
    users = list(session.execute(select(User)).scalars())
    accounts = {
        row.toolhub_user_id: row
        for row in session.execute(
            select(ToolhubAccountProjection).where(
                ToolhubAccountProjection.toolhub_user_id.in_({user.wm_sub for user in users} or {""})
            )
        ).scalars()
    }
    for user in users:
        account = accounts.get(user.wm_sub)
        if (
            account is not None
            and account.wikimedia_global_user_id
            and (user.wikimedia_global_user_id != account.wikimedia_global_user_id)
        ):
            user.wikimedia_global_user_id = account.wikimedia_global_user_id
            touched += 1
        old_person_id = user.person_id
        people_index.link_user(session, user)
        touched += int(old_person_id != user.person_id)
    return touched


def _sync_toolforge_relationships(session: Session) -> dict[str, int]:
    """Project bound LDAP memberships while preserving unbound source rows."""
    accounts = {row.uid_number: row for row in session.execute(select(ToolforgeAccountProjection)).scalars()}
    bindings = {
        row.external_id: row
        for row in session.execute(
            select(PersonAccountBinding).where(
                PersonAccountBinding.provider == PROVIDER_TOOLFORGE,
                PersonAccountBinding.status == STATUS_VERIFIED,
                PersonAccountBinding.revoked_at.is_(None),
            )
        ).scalars()
    }
    by_tool: dict[str, list[dict[str, Any]]] = {}
    unbound = 0
    for membership in session.execute(select(ToolforgeMembershipProjection)).scalars():
        account = accounts.get(membership.uid_number)
        binding = bindings.get(membership.uid_number)
        if account is None or binding is None or binding.person_id is None:
            unbound += 1
            continue
        person = session.get(Person, binding.person_id)
        if person is None:
            unbound += 1
            continue
        catalog_tool_name = f"toolforge-{membership.tool_name}"
        by_tool.setdefault(catalog_tool_name, []).append(
            {
                "display_name": person.display_name or account.uid,
                "toolforge_uid_number": account.uid_number,
                "toolforge_username": account.uid,
                "relationship_type": "maintainer",
                "method": "toolforge_ldap_membership",
                "evidence_key": account.uid_number,
                "verification_status": "verified",
                "confidence": 100,
                "evidence_payload": {
                    "toolforgeUid": account.uid,
                    "toolforgeUidNumber": account.uid_number,
                    "toolforgeToolName": membership.tool_name,
                    "identityBindingMethod": binding.proof_method,
                },
                "checked_at": membership.last_seen_at,
            }
        )
    previous_tools = set(
        session.execute(
            select(ToolRelationshipEvidence.tool_name).where(
                ToolRelationshipEvidence.source == SOURCE_TOOLFORGE_LDAP,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
        ).scalars()
    )
    projected = 0
    for tool_name in sorted(previous_tools | set(by_tool)):
        projected += len(
            people_index.replace_source_evidence(
                session,
                tool_name,
                SOURCE_TOOLFORGE_LDAP,
                by_tool.get(tool_name, []),
            )
        )
    return {"membershipRelationships": projected, "unboundMemberships": unbound}


def synchronize(session: Session) -> dict[str, int]:
    """Hydrate official identities and resolve all safe account bindings."""
    toolhub = _sync_toolhub_bindings(session)
    toolforge = _sync_toolforge_bindings(session)
    users = _hydrate_local_users(session)
    relationships = _sync_toolforge_relationships(session)
    return {"toolhubBindings": toolhub, "usersHydrated": users, **toolforge, **relationships}


def verified_person_for_account(session: Session, provider: str, external_id: str) -> Person | None:
    """Return the person only for a current verified immutable account binding."""
    row = session.execute(
        select(PersonAccountBinding).where(
            PersonAccountBinding.provider == provider,
            PersonAccountBinding.external_id == external_id,
            PersonAccountBinding.status == STATUS_VERIFIED,
            PersonAccountBinding.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    return session.get(Person, row.person_id) if row is not None and row.person_id is not None else None


def candidate_count_for_person(session: Session, person_id: int) -> int:
    """Return pending account candidates for account UI and operator queues."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(PersonAccountBinding)
            .where(
                PersonAccountBinding.person_id == person_id,
                PersonAccountBinding.status == STATUS_CANDIDATE,
                PersonAccountBinding.revoked_at.is_(None),
            )
        )
        or 0
    )
