# SPDX-License-Identifier: GPL-3.0-or-later
"""Central account-to-person binding and identity hydration service."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from backend import canonical_tools, maintainer_index, people_index
from backend.models import (
    ApiCacheMeta,
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
SOURCE_TOOLFORGE_LDAP = maintainer_index.SOURCE_TOOLFORGE_LDAP
TOOLFORGE_RELATIONSHIP_META_KEY = "toolforge_relationship_input_v1"


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


def _binding(
    session: Session,
    provider: str,
    external_id: str,
    binding_index: dict[tuple[str, str], PersonAccountBinding] | None = None,
) -> PersonAccountBinding:
    key = (provider, external_id)
    row = binding_index.get(key) if binding_index is not None else None
    if row is None and binding_index is None:
        row = session.execute(
            select(PersonAccountBinding).where(
                PersonAccountBinding.provider == provider,
                PersonAccountBinding.external_id == external_id,
            )
        ).scalar_one_or_none()
    if row is None:
        row = PersonAccountBinding(provider=provider, external_id=external_id)
        session.add(row)
        if binding_index is not None:
            binding_index[key] = row
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
    binding_index: dict[tuple[str, str], PersonAccountBinding] | None = None,
) -> PersonAccountBinding:
    row = _binding(session, provider, external_id, binding_index)
    if row.status == STATUS_VERIFIED and row.person_id != person_id and status != STATUS_CONFLICT:
        message = f"{provider} account {external_id} is already verified for another person"
        raise _binding_conflict(message)
    now = utcnow()
    changed = (
        row.person_id != person_id
        or row.status != status
        or row.proof_method != proof_method
        or row.confidence != max(0, min(100, confidence))
        or row.evidence != evidence
        or row.verified_by_user_id != verified_by_user_id
        or row.revoked_at is not None
    )
    row.person_id = person_id
    row.status = status
    row.proof_method = proof_method
    row.confidence = max(0, min(100, confidence))
    row.evidence = evidence
    row.verified_by_user_id = verified_by_user_id
    if status == STATUS_VERIFIED and (row.verified_at is None or changed):
        row.verified_at = now
    elif status != STATUS_VERIFIED:
        row.verified_at = None
    row.revoked_at = None
    if changed:
        row.last_seen_at = now
        row.updated_at = now
    return row


def _identifier_people(session: Session) -> dict[tuple[str, str], Person]:
    """Load current identifier owners once for one synchronization transaction."""
    identifiers = list(session.execute(select(PersonIdentifier).where(PersonIdentifier.is_current.is_(True))).scalars())
    person_ids = {row.person_id for row in identifiers}
    people = {
        person.id: person
        for person in session.execute(select(Person).where(Person.id.in_(person_ids or {-1}))).scalars()
    }
    return {
        (row.namespace, row.normalized_value): people[row.person_id] for row in identifiers if row.person_id in people
    }


def _indexed_person(identifiers: dict[tuple[str, str], Person], namespace: str, value: str | None) -> Person | None:
    normalized = _clean(value).casefold()
    return identifiers.get((namespace, normalized)) if normalized else None


def _binding_rows(session: Session) -> dict[tuple[str, str], PersonAccountBinding]:
    return {(row.provider, row.external_id): row for row in session.execute(select(PersonAccountBinding)).scalars()}


def _update_digest(digest: Any, label: str, rows: Any) -> None:  # noqa: ANN401 - hash and SQL row iterables
    digest.update(label.encode())
    for row in rows:
        digest.update(json.dumps(list(row), default=str, separators=(",", ":")).encode())


def _canonical_alias_rows(canonical_names: dict[str, tuple[str, ...]]) -> list[tuple[str, str]]:
    return [
        (project, tool_name)
        for project, tool_names in sorted(canonical_names.items())
        for tool_name in sorted(tool_names)
    ]


def input_fingerprint(session: Session) -> str:
    """Hash identity-relevant projection values, never cache timestamps."""
    digest = hashlib.sha256()
    _update_digest(
        digest,
        "toolhub",
        session.execute(
            select(
                ToolhubAccountProjection.toolhub_user_id,
                ToolhubAccountProjection.username,
                ToolhubAccountProjection.wikimedia_global_user_id,
            ).order_by(ToolhubAccountProjection.toolhub_user_id)
        ),
    )
    _update_digest(
        digest,
        "toolforge",
        session.execute(
            select(
                ToolforgeAccountProjection.uid_number,
                ToolforgeAccountProjection.uid,
                ToolforgeAccountProjection.wikimedia_global_user_id,
                ToolforgeAccountProjection.disabled,
            ).order_by(ToolforgeAccountProjection.uid_number)
        ),
    )
    _update_digest(
        digest,
        "memberships",
        session.execute(
            select(ToolforgeMembershipProjection.uid_number, ToolforgeMembershipProjection.tool_name).order_by(
                ToolforgeMembershipProjection.uid_number,
                ToolforgeMembershipProjection.tool_name,
            )
        ),
    )
    _update_digest(digest, "aliases", _canonical_alias_rows(canonical_tools.names_by_toolforge_project(session)))
    return digest.hexdigest()


def _relationship_fingerprint(
    session: Session,
    canonical_names: dict[str, tuple[str, ...]],
) -> str:
    digest = hashlib.sha256()
    _update_digest(
        digest,
        "bindings",
        session.execute(
            select(
                PersonAccountBinding.external_id,
                PersonAccountBinding.person_id,
                PersonAccountBinding.proof_method,
            )
            .where(
                PersonAccountBinding.provider == PROVIDER_TOOLFORGE,
                PersonAccountBinding.status == STATUS_VERIFIED,
                PersonAccountBinding.revoked_at.is_(None),
            )
            .order_by(PersonAccountBinding.external_id)
        ),
    )
    _update_digest(
        digest,
        "memberships",
        session.execute(
            select(ToolforgeMembershipProjection.uid_number, ToolforgeMembershipProjection.tool_name).order_by(
                ToolforgeMembershipProjection.uid_number,
                ToolforgeMembershipProjection.tool_name,
            )
        ),
    )
    _update_digest(digest, "aliases", _canonical_alias_rows(canonical_names))
    return digest.hexdigest()


def seed_relationship_fingerprint(session: Session) -> int:
    """Mark an existing LDAP relationship projection as current during migration."""
    if session.get(ApiCacheMeta, TOOLFORGE_RELATIONSHIP_META_KEY) is not None:
        return 0
    has_projection = session.scalar(
        select(func.count())
        .select_from(ToolRelationshipEvidence)
        .where(
            ToolRelationshipEvidence.source == SOURCE_TOOLFORGE_LDAP,
            ToolRelationshipEvidence.withdrawn_at.is_(None),
        )
    )
    if not has_projection:
        return 0
    canonical_names = canonical_tools.names_by_toolforge_project(session)
    session.add(
        ApiCacheMeta(
            key=TOOLFORGE_RELATIONSHIP_META_KEY,
            value=_relationship_fingerprint(session, canonical_names),
        )
    )
    return 1


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
    binding_index: dict[tuple[str, str], PersonAccountBinding] | None = None,
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
        binding_index=binding_index,
    )


def _sync_toolhub_bindings(
    session: Session,
    accounts: list[ToolhubAccountProjection],
    identifiers: dict[tuple[str, str], Person],
    bindings: dict[tuple[str, str], PersonAccountBinding],
) -> dict[str, int]:
    stats = {"verified": 0, "conflict": 0}
    for account in accounts:
        toolhub_owner = _indexed_person(identifiers, people_index.NS_TOOLHUB_USER_ID, account.toolhub_user_id)
        wikimedia_owner = _indexed_person(
            identifiers, people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, account.wikimedia_global_user_id
        )
        if toolhub_owner is not None and wikimedia_owner is not None and toolhub_owner.id != wikimedia_owner.id:
            _set_binding(
                session,
                provider=PROVIDER_TOOLHUB,
                external_id=account.toolhub_user_id,
                person_id=None,
                status=STATUS_CONFLICT,
                proof_method=PROOF_TOOLHUB_WIKIMEDIA,
                confidence=100,
                evidence={
                    "reason": "stable_identifier_conflict",
                    "toolhubUserId": account.toolhub_user_id,
                    "wikimediaGlobalUserId": account.wikimedia_global_user_id,
                    "toolhubPersonId": toolhub_owner.public_id,
                    "wikimediaPersonId": wikimedia_owner.public_id,
                },
                binding_index=bindings,
            )
            stats["conflict"] += 1
            continue
        handle_owner = _indexed_person(identifiers, people_index.NS_TOOLHUB_USERNAME, account.username)
        person = toolhub_owner or wikimedia_owner
        identifiers_complete = (
            person is not None
            and toolhub_owner is person
            and (not account.wikimedia_global_user_id or wikimedia_owner is person)
            and handle_owner is person
        )
        if identifiers_complete:
            if person.display_name != account.username:
                person.display_name = account.username
                person.updated_at = account.last_seen_at
        else:
            person = people_index.ensure_official_account_person(
                session,
                toolhub_user_id=account.toolhub_user_id,
                username=account.username,
                wikimedia_global_user_id=account.wikimedia_global_user_id or "",
                checked_at=account.last_seen_at,
            )
            if person is not None:
                identifiers[(people_index.NS_TOOLHUB_USER_ID, account.toolhub_user_id.casefold())] = person
                identifiers[(people_index.NS_TOOLHUB_USERNAME, account.username.casefold())] = person
                if account.wikimedia_global_user_id:
                    identifiers[
                        (people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, account.wikimedia_global_user_id.casefold())
                    ] = person
        if person is None:
            stats["conflict"] += 1
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
            binding_index=bindings,
        )
        stats["verified"] += 1
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
                binding_index=bindings,
            )
            stats["verified"] += 1
    return stats


def _unique_toolhub_handle_candidate(
    account: ToolforgeAccountProjection,
    toolhub_handles: dict[str, list[ToolhubAccountProjection]],
    identifiers: dict[tuple[str, str], Person],
) -> tuple[ToolhubAccountProjection, Person] | None:
    matches = toolhub_handles.get(account.normalized_uid, [])
    if len(matches) != 1:
        return None
    toolhub_account = matches[0]
    person = _indexed_person(identifiers, people_index.NS_TOOLHUB_USER_ID, toolhub_account.toolhub_user_id)
    return (toolhub_account, person) if person is not None else None


def _sync_toolforge_bindings(
    session: Session,
    accounts: list[ToolforgeAccountProjection],
    toolhub_accounts: list[ToolhubAccountProjection],
    identifiers: dict[tuple[str, str], Person],
    bindings: dict[tuple[str, str], PersonAccountBinding],
) -> dict[str, int]:
    toolhub_handles: dict[str, list[ToolhubAccountProjection]] = {}
    for row in toolhub_accounts:
        toolhub_handles.setdefault(row.normalized_username, []).append(row)
    stats = {"verified": 0, "candidate": 0, "conflict": 0, "unresolved": 0}
    for account in accounts:
        global_id = account.wikimedia_global_user_id or ""
        if global_id:
            person = _indexed_person(identifiers, people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, global_id)
            if person is None:
                person = people_index.ensure_person(
                    session,
                    display_name=account.wikimedia_global_name or account.uid,
                    wikimedia_global_user_id=global_id,
                    wiki_username=account.wikimedia_global_name,
                    source=PROOF_TOOLFORGE_SUL,
                )
                identifiers[(people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, global_id.casefold())] = person
            stable_owner = _indexed_person(identifiers, people_index.NS_TOOLFORGE_UID_NUMBER, account.uid_number)
            handle_owner = _indexed_person(identifiers, people_index.NS_TOOLFORGE_USERNAME, account.uid)
            existing = bindings.get((PROVIDER_TOOLFORGE, account.uid_number))
            if (
                existing is not None
                and existing.status == STATUS_VERIFIED
                and existing.person_id == person.id
                and stable_owner is person
                and handle_owner is person
            ):
                stats["verified"] += 1
                continue
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
                    binding_index=bindings,
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
                    binding_index=bindings,
                )
                stats["conflict"] += 1
            else:
                stats["verified"] += 1
                identifiers[(people_index.NS_TOOLFORGE_UID_NUMBER, account.uid_number.casefold())] = person
                identifiers[(people_index.NS_TOOLFORGE_USERNAME, account.uid.casefold())] = person
            continue
        candidate = _unique_toolhub_handle_candidate(account, toolhub_handles, identifiers)
        if candidate is None:
            stats["unresolved"] += 1
            continue
        toolhub_account, person = candidate
        existing = _binding(session, PROVIDER_TOOLFORGE, account.uid_number, bindings)
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
            binding_index=bindings,
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
    canonical_names = canonical_tools.names_by_toolforge_project(session)
    relationship_fingerprint = _relationship_fingerprint(session, canonical_names)
    relationship_marker = session.get(ApiCacheMeta, TOOLFORGE_RELATIONSHIP_META_KEY)
    if relationship_marker is not None and relationship_marker.value == relationship_fingerprint:
        return {
            "membershipRelationships": 0,
            "canonicalMembershipRelationships": 0,
            "fallbackMembershipRelationships": 0,
            "unboundMemberships": 0,
            "relationshipCacheHit": 1,
        }
    by_tool: dict[str, list[dict[str, Any]]] = {}
    unbound = 0
    canonical_relationships = 0
    fallback_relationships = 0
    person_ids = {row.person_id for row in bindings.values() if row.person_id is not None}
    people = {
        person.id: person
        for person in session.execute(select(Person).where(Person.id.in_(person_ids or {-1}))).scalars()
    }
    for membership in session.execute(select(ToolforgeMembershipProjection)).scalars():
        account = accounts.get(membership.uid_number)
        binding = bindings.get(membership.uid_number)
        if account is None or binding is None or binding.person_id is None:
            unbound += 1
            continue
        person = people.get(binding.person_id)
        if person is None:
            unbound += 1
            continue
        matched_names = canonical_names.get(membership.tool_name.casefold(), ())
        catalog_tool_names = matched_names or (f"toolforge-{membership.tool_name}",)
        canonical_relationships += len(matched_names)
        fallback_relationships += int(not matched_names)
        for catalog_tool_name in catalog_tool_names:
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
                        "canonicalToolName": catalog_tool_name,
                        "toolMappingMethod": "canonical_project_alias" if matched_names else "conventional_fallback",
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
    if relationship_marker is None:
        session.add(ApiCacheMeta(key=TOOLFORGE_RELATIONSHIP_META_KEY, value=relationship_fingerprint))
    else:
        relationship_marker.value = relationship_fingerprint
        relationship_marker.updated_at = utcnow()
    return {
        "membershipRelationships": projected,
        "canonicalMembershipRelationships": canonical_relationships,
        "fallbackMembershipRelationships": fallback_relationships,
        "unboundMemberships": unbound,
        "relationshipCacheHit": 0,
    }


def synchronize(session: Session) -> dict[str, int]:
    """Hydrate official identities and resolve all safe account bindings."""
    toolhub_accounts = list(session.execute(select(ToolhubAccountProjection)).scalars())
    toolforge_accounts = list(session.execute(select(ToolforgeAccountProjection)).scalars())
    identifiers = _identifier_people(session)
    bindings = _binding_rows(session)
    toolhub = _sync_toolhub_bindings(session, toolhub_accounts, identifiers, bindings)
    toolforge = _sync_toolforge_bindings(
        session,
        toolforge_accounts,
        toolhub_accounts,
        identifiers,
        bindings,
    )
    users = _hydrate_local_users(session)
    relationships = _sync_toolforge_relationships(session)
    return {
        "toolhubBindings": toolhub["verified"],
        "toolhubConflicts": toolhub["conflict"],
        "usersHydrated": users,
        **toolforge,
        **relationships,
    }


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
