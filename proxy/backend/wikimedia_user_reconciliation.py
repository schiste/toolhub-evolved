# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify user-space tool authors and maintainers through stable identity."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import identity_graph, people_index, projection_policy, toolinfo_authors, wikimedia_urls
from backend.models import (
    ApiCacheMeta,
    CanonicalToolCache,
    Person,
    PersonAccountBinding,
    PersonIdentifier,
    ToolforgeAccountProjection,
    ToolRelationshipEvidence,
    utcnow,
)
from backend.sync import AUTHOR_CLAIM_VERIFIED, PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SOURCE = "wikimedia_user_space_toolforge"
METHOD = "wikimedia_user_space_centralauth_author"
MAINTAINER_METHOD = "wikimedia_user_space_namespace_owner"
PROOF_METHOD = "wikimedia_user_space_exact_toolforge_handle"
META_KEY = "wikimedia_user_space_reconciliation_v1"
CONFIDENCE = 95
RULES_FINGERPRINT = projection_policy.module_fingerprint(
    sys.modules[__name__],
    namespace="wikimedia-user-space-toolforge-policy-v1",
)


@dataclass(frozen=True)
class UserSpaceToolCandidate:
    """One canonical tool hosted below a Wikimedia user namespace."""

    tool_name: str
    url: str
    domain: str
    page_title: str
    owner: str
    normalized_owner: str
    matched_author: str = ""


@dataclass(frozen=True)
class WikimediaPerson:
    """One rename-safe CentralAuth person indexed by a current wiki handle."""

    person: Person
    global_user_id: str
    wiki_username: str


def _clean(value: Any, limit: int = 2000) -> str:  # noqa: ANN401 - official API JSON
    return str(value or "").strip()[:limit]


def _author_values(record: dict[str, Any]) -> list[str]:
    return [
        value
        for assertion in toolinfo_authors.author_assertions(record)
        for value in (assertion.display_name, assertion.wiki_username, assertion.developer_username)
        if _clean(value, 255)
    ]


def _tool_candidates(s: Session) -> list[UserSpaceToolCandidate]:
    candidates: list[UserSpaceToolCandidate] = []
    rows = s.execute(select(CanonicalToolCache.tool_name, CanonicalToolCache.record)).all()
    for tool_name, raw_record in rows:
        record = raw_record if isinstance(raw_record, dict) else {}
        url = _clean(record.get("url"))
        page = wikimedia_urls.user_space_page(url)
        if page is None:
            continue
        normalized_owner = wikimedia_urls.normalized_username(page.username)
        matched = next(
            (
                value
                for value in _author_values(record)
                if wikimedia_urls.normalized_username(value) == normalized_owner
            ),
            "",
        )
        if not normalized_owner:
            continue
        candidates.append(
            UserSpaceToolCandidate(
                tool_name=tool_name,
                url=url,
                domain=page.domain,
                page_title=page.title,
                owner=page.username,
                normalized_owner=normalized_owner,
                matched_author=matched,
            )
        )
    return sorted(candidates, key=lambda row: (row.normalized_owner, row.tool_name))


def _toolforge_accounts(s: Session) -> dict[str, list[ToolforgeAccountProjection]]:
    by_handle: dict[str, list[ToolforgeAccountProjection]] = {}
    accounts = s.execute(
        select(ToolforgeAccountProjection)
        .where(ToolforgeAccountProjection.disabled.is_(False))
        .order_by(ToolforgeAccountProjection.uid_number)
    ).scalars()
    for account in accounts:
        normalized = wikimedia_urls.normalized_username(account.developer_username)
        if normalized:
            by_handle.setdefault(normalized, []).append(account)
    return by_handle


def _wikimedia_people(s: Session) -> dict[str, list[WikimediaPerson]]:
    identifiers = list(
        s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace.in_(
                    (people_index.NS_WIKI_USERNAME, people_index.NS_WIKIMEDIA_GLOBAL_USER_ID)
                ),
                PersonIdentifier.is_current.is_(True),
            )
        ).scalars()
    )
    globals_by_person: dict[int, set[str]] = {}
    handles_by_person: dict[int, list[str]] = {}
    for row in identifiers:
        if row.namespace == people_index.NS_WIKIMEDIA_GLOBAL_USER_ID:
            globals_by_person.setdefault(row.person_id, set()).add(row.value)
        else:
            handles_by_person.setdefault(row.person_id, []).append(row.value)
    by_handle: dict[str, list[WikimediaPerson]] = {}
    for person_id, handles in handles_by_person.items():
        global_ids = globals_by_person.get(person_id, set())
        person = s.get(Person, person_id)
        if person is None or len(global_ids) != 1:
            continue
        global_user_id = next(iter(global_ids))
        for handle in handles:
            normalized = wikimedia_urls.normalized_username(handle)
            if normalized:
                by_handle.setdefault(normalized, []).append(
                    WikimediaPerson(
                        person=person,
                        global_user_id=global_user_id,
                        wiki_username=handle,
                    )
                )
    return by_handle


def _fingerprint(s: Session) -> str:
    """Hash only rule inputs so unchanged hourly runs perform no writes."""
    digest = hashlib.sha256(RULES_FINGERPRINT.encode())

    def update(value: Any) -> None:  # noqa: ANN401 - rows include JSON and datetimes
        digest.update(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode())

    for tool_name, record in s.execute(
        select(CanonicalToolCache.tool_name, CanonicalToolCache.record).order_by(CanonicalToolCache.tool_name)
    ):
        source = record if isinstance(record, dict) else {}
        update((tool_name, source.get("url"), source.get("author")))
    for row in s.execute(select(ToolforgeAccountProjection).order_by(ToolforgeAccountProjection.uid_number)).scalars():
        update((row.uid_number, row.uid, row.developer_username, row.disabled))
    for row in s.execute(
        select(PersonIdentifier)
        .where(
            PersonIdentifier.namespace.in_((people_index.NS_WIKI_USERNAME, people_index.NS_WIKIMEDIA_GLOBAL_USER_ID))
        )
        .order_by(PersonIdentifier.id)
    ).scalars():
        update((row.person_id, row.namespace, row.value, row.is_current))
    for row in s.execute(
        select(PersonAccountBinding)
        .where(PersonAccountBinding.provider == identity_graph.PROVIDER_TOOLFORGE)
        .order_by(PersonAccountBinding.id)
    ).scalars():
        update((row.external_id, row.person_id, row.status, row.proof_method, row.revoked_at))
    for row in s.execute(
        select(ToolRelationshipEvidence)
        .where(ToolRelationshipEvidence.source == SOURCE)
        .order_by(ToolRelationshipEvidence.id)
    ).scalars():
        update(
            (
                row.tool_name,
                row.person_id,
                row.relationship_type,
                row.method,
                row.verification_status,
                row.withdrawn_at,
            )
        )
    return digest.hexdigest()


def empty_stats(*, cache_hit: int = 0) -> dict[str, int]:
    return {
        "candidateTools": 0,
        "verifiedTools": 0,
        "authorEvidence": 0,
        "maintainerEvidence": 0,
        "accountsVerified": 0,
        "accountsBound": 0,
        "bindingConflicts": 0,
        "ambiguousToolforgeAccounts": 0,
        "ambiguousWikimediaIdentities": 0,
        "missingToolforgeAccounts": 0,
        "missingWikimediaIdentities": 0,
        "retiredTools": 0,
        "cacheHit": cache_hit,
    }


def synchronize(  # noqa: C901, PLR0912, PLR0915 - ordered fail-closed reconciliation policy
    s: Session,
) -> dict[str, int]:
    """Publish role-specific evidence for deterministic three-way matches."""
    current_fingerprint = _fingerprint(s)
    marker = s.get(ApiCacheMeta, META_KEY)
    if marker is not None and marker.value == current_fingerprint:
        return empty_stats(cache_hit=1)

    stats = empty_stats()
    candidates = _tool_candidates(s)
    stats["candidateTools"] = len(candidates)
    accounts = _toolforge_accounts(s)
    people = _wikimedia_people(s)
    bindings = {
        (row.provider, row.external_id): row
        for row in s.execute(
            select(PersonAccountBinding).where(PersonAccountBinding.provider == identity_graph.PROVIDER_TOOLFORGE)
        ).scalars()
    }
    candidates_by_owner: dict[str, list[UserSpaceToolCandidate]] = {}
    for candidate in candidates:
        candidates_by_owner.setdefault(candidate.normalized_owner, []).append(candidate)

    observations_by_tool: dict[str, list[dict[str, Any]]] = {}
    for owner, tools in candidates_by_owner.items():
        matching_people = people.get(owner, [])
        if not matching_people:
            stats["missingWikimediaIdentities"] += 1
            continue
        person_ids = {row.person.id for row in matching_people}
        if len(person_ids) != 1:
            stats["ambiguousWikimediaIdentities"] += 1
            continue
        identity = min(matching_people, key=lambda row: (row.global_user_id, row.wiki_username))
        account: ToolforgeAccountProjection | None = None
        matching_accounts = accounts.get(owner, [])
        if not matching_accounts:
            stats["missingToolforgeAccounts"] += 1
        elif len(matching_accounts) != 1:
            stats["ambiguousToolforgeAccounts"] += 1
        else:
            candidate_account = matching_accounts[0]
            existing = bindings.get((identity_graph.PROVIDER_TOOLFORGE, candidate_account.uid_number))
            was_verified = bool(
                existing is not None
                and existing.status == identity_graph.STATUS_VERIFIED
                and existing.person_id == identity.person.id
                and existing.revoked_at is None
            )
            try:
                identity_graph.bind_toolforge_account(
                    s,
                    account=candidate_account,
                    person=identity.person,
                    proof_method=PROOF_METHOD,
                    confidence=CONFIDENCE,
                    evidence={
                        "wikimediaGlobalUserId": identity.global_user_id,
                        "wikimediaUsername": identity.wiki_username,
                        "wikimediaDomains": sorted({tool.domain for tool in tools}),
                        "toolforgeUidNumber": candidate_account.uid_number,
                        "toolforgeDeveloperUsername": candidate_account.developer_username,
                        "toolforgeShellUsername": candidate_account.uid,
                        "matchedToolNames": [tool.tool_name for tool in tools],
                    },
                    binding_index=bindings,
                )
            except identity_graph.IdentityBindingConflictError:
                stats["bindingConflicts"] += 1
            else:
                account = candidate_account
                stats["accountsVerified"] += 1
                stats["accountsBound"] += int(not was_verified)
        for tool in tools:
            evidence_payload = {
                "wikimediaDomain": tool.domain,
                "wikimediaPageTitle": tool.page_title,
                "wikimediaPageOwner": tool.owner,
                "wikimediaUsername": identity.wiki_username,
                "wikimediaGlobalUserId": identity.global_user_id,
            }
            common = {
                "display_name": identity.person.display_name or identity.wiki_username,
                "wikimedia_global_user_id": identity.global_user_id,
                "wiki_username": identity.wiki_username,
                "evidence_key": identity.global_user_id,
                "verification_status": AUTHOR_CLAIM_VERIFIED,
                "confidence": CONFIDENCE,
                "evidence_url": tool.url,
                "evidence_payload": evidence_payload,
                "checked_at": utcnow(),
            }
            if account is not None:
                common |= {
                    "toolforge_uid_number": account.uid_number,
                    "toolforge_username": account.developer_username,
                    "evidence_payload": evidence_payload
                    | {
                        "toolforgeDeveloperUsername": account.developer_username,
                        "toolforgeUidNumber": account.uid_number,
                        "identityBindingMethod": PROOF_METHOD,
                    },
                }
            observations = [
                common
                | {
                    "relationship_type": PERSON_REL_MAINTAINER,
                    "method": MAINTAINER_METHOD,
                }
            ]
            if tool.matched_author:
                observations.append(
                    common
                    | {
                        "relationship_type": PERSON_REL_AUTHOR,
                        "method": METHOD,
                        "evidence_payload": common["evidence_payload"] | {"matchedAuthor": tool.matched_author},
                    }
                )
            observations_by_tool[tool.tool_name] = observations

    previous_tools = set(
        s.execute(
            select(ToolRelationshipEvidence.tool_name).where(
                ToolRelationshipEvidence.source == SOURCE,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
        ).scalars()
    )
    for tool_name in sorted(previous_tools | set(observations_by_tool)):
        rows = people_index.replace_source_evidence(
            s,
            tool_name,
            SOURCE,
            observations_by_tool.get(tool_name, []),
        )
        stats["authorEvidence"] += sum(row.relationship_type == PERSON_REL_AUTHOR for row in rows)
        stats["maintainerEvidence"] += sum(row.relationship_type == PERSON_REL_MAINTAINER for row in rows)
    stats["verifiedTools"] = len(observations_by_tool)
    stats["retiredTools"] = len(previous_tools - set(observations_by_tool))

    final_fingerprint = _fingerprint(s)
    if marker is None:
        s.add(ApiCacheMeta(key=META_KEY, value=final_fingerprint))
    else:
        marker.value = final_fingerprint
        marker.updated_at = utcnow()
    return stats
