# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn indexed toolinfo provenance into auditable people relationships."""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from sqlalchemy import and_, func, or_, select

from backend import canonical_tools, db, identity_graph, people_index, projection_policy, toolinfo_authors
from backend.models import (
    ApiCacheMeta,
    CanonicalToolCache,
    Person,
    PersonAccountBinding,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationRun,
    ToolAuthorClaim,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolinfoAuthorBinding,
    ToolinfoSource,
    ToolinfoSourceAttestation,
    ToolinfoSourceGeneration,
    ToolinfoSourceItem,
    ToolRelationshipEvidence,
    User,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SOURCE_AUTHOR_ATTESTATION = "toolinfo_source_attestation"
SOURCE_TARGET_MEMBERSHIP = "toolinfo_target_toolforge"
METHOD_SOURCE_CONTROLLER = "toolinfo_source_controller"
METHOD_VERIFIED_ANCHOR = "toolinfo_verified_author_anchor"
METHOD_STRUCTURED_HANDLE = "toolinfo_structured_author_handle"
METHOD_TARGET_MEMBERSHIP = "toolinfo_target_ldap_membership"

CLASS_SINGLE = "single_person_controlled"
CLASS_GROUP = "group_controlled"
CLASS_SERVICE = "service_registered"
CLASS_UNKNOWN = "unknown"
CLASS_CONFLICT = "conflicted"

STATUS_VERIFIED = "verified"
STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"
STATUS_CONFLICT = "conflict"
RECONCILIATION_RUN_MODE = "source-evidence"
RULES_VERSION = projection_policy.module_fingerprint(
    sys.modules[__name__],
    namespace="source-attestation-policy-v1",
)
RULES_META_KEY = "source_attestation_rules_version"
GENERATION_COMPARISON_DEPTH = 2
FULL_AUDIT_BATCH_SIZE = 10
SOURCE_WRITER_LOCK = "toolhub-evolved:source-attestation-writes"


class SourceAttestationBusyError(RuntimeError):
    """Raised when another worker is publishing source-derived evidence."""

    def __init__(self) -> None:
        """Create the operator-facing lock timeout error."""
        super().__init__("source-attestation writer remained busy for 120 seconds")


# A per-record signature anchors that record's signer through the ordinary
# relationship graph. It does not prove control of sibling feed records.
STRONG_CONTROL_METHODS = {AUTHOR_CLAIM_TOOLINFO_URL_CONTROL}


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - stored/external JSON
    return " ".join(str(value or "").split()).strip()[:limit]


def _normalized_identity(value: Any) -> str:  # noqa: ANN401 - identity labels
    clean = _clean(value).replace("_", " ")
    prefix, separator, remainder = clean.partition(":")
    if separator and prefix.casefold() == "user":
        clean = remainder.strip()
    return " ".join(clean.split()).casefold()


def _normalized_url(value: str) -> str:
    parsed = urlparse(_clean(value, 2000))
    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").casefold()
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    return urlunparse((scheme, f"{host}{port}", path, "", parsed.query, ""))


def toolforge_project_from_source_url(url: str) -> str:
    """Return the Toolforge project serving a source, without special cases."""
    host = (urlparse(url).hostname or "").casefold()
    return host.removesuffix(".toolforge.org") if host.endswith(".toolforge.org") else ""


def wiki_user_from_source_url(url: str) -> str:
    """Extract a user namespace owner from a Wikimedia raw-page source."""
    parsed = urlparse(url)
    candidates = [parse_qs(parsed.query).get("title", [""])[0]]
    path = unquote(parsed.path)
    if "/wiki/" in path:
        candidates.append(path.split("/wiki/", 1)[1])
    for candidate in candidates:
        title = _clean(candidate)
        prefix, separator, remainder = title.partition(":")
        if separator and prefix.casefold() == "user":
            return remainder.split("/", 1)[0].strip()
    return ""


def _person_aliases(s: Session, person_id: int) -> set[str]:
    person = s.get(Person, person_id)
    values = [person.display_name] if person is not None else []
    values.extend(
        row.value
        for row in s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.person_id == person_id,
                PersonIdentifier.is_current.is_(True),
            )
        ).scalars()
    )
    return {_normalized_identity(value) for value in values if _normalized_identity(value)}


def _person_identity(s: Session, person_id: int) -> dict[str, str]:
    fields = {
        people_index.NS_TOOLHUB_USER_ID: "toolhub_user_id",
        people_index.NS_WIKIMEDIA_GLOBAL_USER_ID: "wikimedia_global_user_id",
        people_index.NS_TOOLFORGE_UID_NUMBER: "toolforge_uid_number",
        people_index.NS_TOOLHUB_USERNAME: "toolhub_username",
        people_index.NS_TOOLFORGE_USERNAME: "toolforge_username",
        people_index.NS_TOOLFORGE_SHELL_USERNAME: "toolforge_shell_username",
        people_index.NS_WIKI_USERNAME: "wiki_username",
    }
    out = dict.fromkeys(fields.values(), "")
    for row in s.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.person_id == person_id,
            PersonIdentifier.is_current.is_(True),
        )
    ).scalars():
        if field := fields.get(row.namespace):
            out[field] = row.value
    return out


def _verified_person_for_handle(s: Session, namespace: str, value: str) -> Person | None:
    expected = _normalized_identity(value)
    if not expected:
        return None
    rows = list(
        s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace == namespace,
                PersonIdentifier.is_current.is_(True),
            )
        ).scalars()
    )
    person_ids = {row.person_id for row in rows if _normalized_identity(row.value) == expected}
    if len(person_ids) != 1:
        return None
    person_id = next(iter(person_ids))
    return s.get(Person, person_id) if person_id in people_index.public_identity_ids(s, {person_id}) else None


def _claim_controllers(s: Session, source: ToolinfoSource) -> set[int]:
    now = utcnow()
    source_url = _normalized_url(source.url)
    rows = s.execute(
        select(ToolAuthorClaim, User)
        .join(User, User.id == ToolAuthorClaim.user_id)
        .where(
            ToolAuthorClaim.verification_method.in_(STRONG_CONTROL_METHODS),
            ToolAuthorClaim.verification_status == AUTHOR_CLAIM_VERIFIED,
            ToolAuthorClaim.revoked_at.is_(None),
            or_(ToolAuthorClaim.expires_at.is_(None), ToolAuthorClaim.expires_at > now),
            User.person_id.is_not(None),
        )
    ).all()
    return {
        user.person_id
        for claim, user in rows
        if user.person_id is not None and _normalized_url(claim.evidence_url or "") == source_url
    }


def _toolforge_controller_rows(
    s: Session, project: str
) -> list[tuple[ToolforgeAccountProjection, PersonAccountBinding | None]]:
    if not project:
        return []
    rows = s.execute(
        select(ToolforgeAccountProjection, PersonAccountBinding)
        .join(
            ToolforgeMembershipProjection,
            ToolforgeMembershipProjection.uid_number == ToolforgeAccountProjection.uid_number,
        )
        .outerjoin(
            PersonAccountBinding,
            and_(
                PersonAccountBinding.provider == identity_graph.PROVIDER_TOOLFORGE,
                PersonAccountBinding.external_id == ToolforgeAccountProjection.uid_number,
                PersonAccountBinding.status == identity_graph.STATUS_VERIFIED,
                PersonAccountBinding.revoked_at.is_(None),
            ),
        )
        .where(
            func.lower(ToolforgeMembershipProjection.tool_name) == project.casefold(),
            ToolforgeAccountProjection.disabled.is_(False),
        )
    ).all()
    return list(rows)


def _resolve_attestation(  # noqa: PLR0915 - explicit precedence is the source-control trust policy
    s: Session, source: ToolinfoSource
) -> ToolinfoSourceAttestation:
    now = utcnow()
    proof_people = _claim_controllers(s, source)
    project = toolforge_project_from_source_url(source.url)
    project_rows = _toolforge_controller_rows(s, project)
    wiki_user = wiki_user_from_source_url(source.url)
    wiki_person = _verified_person_for_handle(s, people_index.NS_WIKI_USERNAME, wiki_user) if wiki_user else None

    classification = CLASS_UNKNOWN
    status = STATUS_UNRESOLVED
    controller_person_id = None
    method = ""
    confidence = 0
    evidence: dict[str, Any] = {"sourceUrl": source.url}
    if len(proof_people) == 1:
        classification = CLASS_SINGLE
        status = STATUS_VERIFIED
        controller_person_id = next(iter(proof_people))
        method = "challenged_source_control"
        confidence = 100
    elif len(proof_people) > 1:
        classification = CLASS_CONFLICT
        status = STATUS_CONFLICT
        method = "conflicting_source_proofs"
        confidence = 100
        evidence["controllerPersonIds"] = sorted(proof_people)
    elif wiki_person is not None:
        classification = CLASS_SINGLE
        status = STATUS_VERIFIED
        controller_person_id = wiki_person.id
        method = "wikimedia_user_page_control"
        confidence = 95
        evidence["wikiUsername"] = wiki_user
    elif project_rows:
        evidence["toolforgeProject"] = project
        evidence["activeMemberCount"] = len(project_rows)
        if len(project_rows) > 1:
            classification = CLASS_GROUP
            method = "toolforge_project_membership"
            confidence = 100
        else:
            account, binding = project_rows[0]
            evidence["toolforgeUidNumber"] = account.uid_number
            if binding is not None and binding.person_id is not None:
                classification = CLASS_SINGLE
                status = STATUS_VERIFIED
                controller_person_id = binding.person_id
                method = "toolforge_single_project_controller"
                confidence = 100
    elif (source.created_by_username or "").casefold() in {"toolhub", "admin", "administrator"}:
        classification = CLASS_SERVICE
        method = "official_registry_service_account"

    row = s.get(ToolinfoSourceAttestation, source.id)
    if row is None:
        row = ToolinfoSourceAttestation(source_id=source.id)
        s.add(row)
    row.classification = classification
    row.status = status
    row.controller_person_id = controller_person_id
    row.controller_count = len(proof_people) or len(project_rows) or int(wiki_person is not None)
    row.method = method
    row.confidence = confidence
    row.evidence = evidence
    row.checked_at = now
    row.last_error = None
    row.updated_at = now
    return row


def _anchor_people(s: Session, items: list[ToolinfoSourceItem]) -> dict[str, set[int]]:
    """Return stable people whose verified tool edge corroborates an author token."""
    names = {item.tool_name for item in items}
    if not names:
        return {}
    rows = list(
        s.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name.in_(names),
                ToolRelationshipEvidence.verification_status == AUTHOR_CLAIM_VERIFIED,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
                ToolRelationshipEvidence.source.not_in({SOURCE_AUTHOR_ATTESTATION, SOURCE_TARGET_MEMBERSHIP}),
            )
        ).scalars()
    )
    stable_ids = people_index.public_identity_ids(s, {row.person_id for row in rows})
    aliases = {person_id: _person_aliases(s, person_id) for person_id in stable_ids}
    by_label: dict[str, set[int]] = defaultdict(set)
    items_by_name = {item.tool_name: item for item in items}
    for row in rows:
        item = items_by_name.get(row.tool_name)
        if item is None or row.person_id not in stable_ids or not isinstance(item.payload, dict):
            continue
        for assertion in toolinfo_authors.author_assertions(item.payload):
            if _normalized_identity(assertion.display_name) in aliases[row.person_id]:
                by_label[assertion.normalized_label].add(row.person_id)
    return by_label


def _verified_handle_index(s: Session) -> dict[tuple[str, str], int]:
    namespaces = {people_index.NS_TOOLFORGE_USERNAME, people_index.NS_WIKI_USERNAME}
    rows = list(
        s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace.in_(namespaces),
                PersonIdentifier.is_current.is_(True),
            )
        ).scalars()
    )
    stable_ids = people_index.public_identity_ids(s, {row.person_id for row in rows})
    return {
        (row.namespace, _normalized_identity(row.value)): row.person_id
        for row in rows
        if row.person_id in stable_ids and _normalized_identity(row.value)
    }


def _structured_people(
    assertion: toolinfo_authors.AuthorAssertion,
    handle_index: dict[tuple[str, str], int],
) -> set[int]:
    people: set[int] = set()
    for namespace, value in (
        (people_index.NS_TOOLFORGE_USERNAME, assertion.developer_username),
        (people_index.NS_WIKI_USERNAME, assertion.wiki_username),
    ):
        if person_id := handle_index.get((namespace, _normalized_identity(value))):
            people.add(person_id)
    return people


def _record_conflict(  # noqa: PLR0913, PLR0917 - conflict provenance remains explicit
    s: Session,
    run_id: int,
    source: ToolinfoSource,
    label: str,
    person_ids: set[int],
    reason: str,
) -> None:
    value = f"{source.id}:{label}"[:255]
    row = s.execute(
        select(PersonReconciliationConflict).where(
            PersonReconciliationConflict.conflict_type == "toolinfo_source_identity",
            PersonReconciliationConflict.value == value,
            PersonReconciliationConflict.status == "pending",
        )
    ).scalar_one_or_none()
    details = {
        "reason": reason,
        "sourceId": source.id,
        "sourceUrl": source.url,
        "authorLabel": label,
        "candidatePersonIds": [s.get(Person, person_id).public_id for person_id in sorted(person_ids)],
    }
    if row is None:
        s.add(
            PersonReconciliationConflict(
                run_id=run_id,
                person_id=next(iter(person_ids), None),
                conflict_type="toolinfo_source_identity",
                value=value,
                details=details,
            )
        )
    else:
        row.run_id = run_id
        row.details = details
        row.last_seen_at = utcnow()


def _refresh_bindings(  # noqa: C901, PLR0913, PLR0915, PLR0917 - one pass applies the ordered binding trust policy
    s: Session,
    source: ToolinfoSource,
    attestation: ToolinfoSourceAttestation,
    items: list[ToolinfoSourceItem],
    run_id: int,
    handle_index: dict[tuple[str, str], int],
) -> dict[str, int]:
    now = utcnow()
    assertions_by_label: dict[str, list[toolinfo_authors.AuthorAssertion]] = defaultdict(list)
    for item in items:
        if isinstance(item.payload, dict):
            for assertion in toolinfo_authors.author_assertions(item.payload):
                assertions_by_label[assertion.normalized_label].append(assertion)
    anchors = _anchor_people(s, items)
    controller_id = attestation.controller_person_id if attestation.status == STATUS_VERIFIED else None
    controller_aliases = _person_aliases(s, controller_id) if controller_id is not None else set()
    existing = {
        row.normalized_label: row
        for row in s.execute(
            select(ToolinfoAuthorBinding).where(ToolinfoAuthorBinding.source_id == source.id)
        ).scalars()
    }
    stats = {"verified": 0, "resolved": 0, "unresolved": 0, "conflicts": 0}
    for label, assertions in assertions_by_label.items():
        strong_people = set(anchors.get(label, set()))
        if controller_id is not None and _normalized_identity(assertions[0].display_name) in controller_aliases:
            strong_people.add(controller_id)
        structured_people = set().union(*(_structured_people(assertion, handle_index) for assertion in assertions))
        candidates = strong_people | structured_people
        if len(candidates) > 1:
            status = STATUS_CONFLICT
            method = "conflicting_source_identity_evidence"
            confidence = 100
            person_id = None
            _record_conflict(s, run_id, source, label, candidates, method)
            stats["conflicts"] += 1
        elif strong_people:
            status = STATUS_VERIFIED
            person_id = next(iter(strong_people))
            method = METHOD_VERIFIED_ANCHOR if anchors.get(label) else METHOD_SOURCE_CONTROLLER
            confidence = 95
            stats["verified"] += 1
        elif structured_people:
            status = STATUS_RESOLVED
            person_id = next(iter(structured_people))
            method = METHOD_STRUCTURED_HANDLE
            confidence = 80
            stats["resolved"] += 1
        else:
            status = STATUS_UNRESOLVED
            person_id = None
            method = "display_only"
            confidence = 0
            stats["unresolved"] += 1
        row = existing.get(label)
        if row is None:
            row = ToolinfoAuthorBinding(source_id=source.id, normalized_label=label, first_seen_at=now)
            s.add(row)
        sample = assertions[0]
        row.observed_label = sample.display_name
        row.person_id = person_id
        row.status = status
        row.method = method
        row.confidence = confidence
        row.evidence = {
            "sourceId": source.id,
            "sourceUrl": source.url,
            "rawAuthors": list(dict.fromkeys(assertion.raw_value for assertion in assertions)),
            "legacyDelimited": any(assertion.legacy_delimited for assertion in assertions),
            "occurrences": len(assertions),
            "controllerMethod": attestation.method,
        }
        row.last_seen_at = now
        row.withdrawn_at = None
        row.updated_at = now
    for label, row in existing.items():
        if label not in assertions_by_label and row.withdrawn_at is None:
            row.withdrawn_at = now
            row.updated_at = now
    return stats


def _observations_for_tool(  # noqa: PLR0913, PLR0917 - preloaded indexes prevent per-tool queries
    tool_name: str,
    items: list[tuple[ToolinfoSourceItem, ToolinfoSource]],
    bindings: dict[tuple[int, str], ToolinfoAuthorBinding],
    members_by_project: dict[str, list[tuple[ToolforgeAccountProjection, PersonAccountBinding]]],
    identities: dict[int, dict[str, str]],
    display_names: dict[int, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    authors: list[dict[str, Any]] = []
    maintainers: list[dict[str, Any]] = []
    for item, source in items:
        if not isinstance(item.payload, dict):
            continue
        for assertion in toolinfo_authors.author_assertions(item.payload):
            binding = bindings.get((source.id, assertion.normalized_label))
            identity = identities.get(binding.person_id, {}) if binding is not None and binding.person_id else {}
            authors.append(
                {
                    "display_name": assertion.display_name,
                    **identity,
                    "relationship_type": PERSON_REL_AUTHOR,
                    "method": binding.method if binding is not None else "display_only",
                    "evidence_key": f"{source.id}:{assertion.position}:{assertion.normalized_label}"[:255],
                    "verification_status": (
                        AUTHOR_CLAIM_VERIFIED
                        if binding is not None and binding.status == STATUS_VERIFIED
                        else "unverified"
                    ),
                    "confidence": binding.confidence if binding is not None else 0,
                    "evidence_url": source.url,
                    "evidence_payload": {
                        "sourceId": source.id,
                        "sourceKind": source.source_kind,
                        "rawAuthor": assertion.raw_value,
                        "authorPosition": assertion.position,
                        "legacyDelimited": assertion.legacy_delimited,
                        "bindingStatus": binding.status if binding is not None else STATUS_UNRESOLVED,
                    },
                    "checked_at": source.last_fetched_at or item.last_seen_at,
                }
            )
        for project in canonical_tools.toolforge_project_names(tool_name, item.payload):
            for account, binding in members_by_project.get(project.casefold(), []):
                assert binding.person_id is not None  # noqa: S101 - index contains only bound accounts
                maintainers.append(
                    {
                        "display_name": display_names.get(
                            binding.person_id,
                            account.developer_username or account.uid,
                        ),
                        **identities.get(binding.person_id, {}),
                        "relationship_type": PERSON_REL_MAINTAINER,
                        "method": METHOD_TARGET_MEMBERSHIP,
                        "evidence_key": f"{source.id}:{project}:{account.uid_number}"[:255],
                        "verification_status": AUTHOR_CLAIM_VERIFIED,
                        "confidence": 100,
                        "evidence_url": source.url,
                        "evidence_payload": {
                            "sourceId": source.id,
                            "toolforgeProject": project,
                            "toolforgeUidNumber": account.uid_number,
                            "toolforgeDeveloperUsername": account.developer_username,
                            "toolforgeShellUsername": account.uid,
                            "identityBindingMethod": binding.proof_method,
                        },
                        "checked_at": source.last_fetched_at or item.last_seen_at,
                    }
                )
    return authors, maintainers


def _verified_members_by_project(
    s: Session,
) -> dict[str, list[tuple[ToolforgeAccountProjection, PersonAccountBinding]]]:
    rows = s.execute(
        select(ToolforgeMembershipProjection, ToolforgeAccountProjection, PersonAccountBinding)
        .join(
            ToolforgeAccountProjection,
            ToolforgeAccountProjection.uid_number == ToolforgeMembershipProjection.uid_number,
        )
        .join(
            PersonAccountBinding,
            and_(
                PersonAccountBinding.provider == identity_graph.PROVIDER_TOOLFORGE,
                PersonAccountBinding.external_id == ToolforgeAccountProjection.uid_number,
                PersonAccountBinding.status == identity_graph.STATUS_VERIFIED,
                PersonAccountBinding.person_id.is_not(None),
                PersonAccountBinding.revoked_at.is_(None),
            ),
        )
        .where(ToolforgeAccountProjection.disabled.is_(False))
    ).all()
    out: dict[str, list[tuple[ToolforgeAccountProjection, PersonAccountBinding]]] = defaultdict(list)
    for membership, account, binding in rows:
        out[membership.tool_name.casefold()].append((account, binding))
    return out


def refresh_tool_names(s: Session, tool_names: list[str]) -> dict[str, int]:
    """Rebuild source-derived edges from every valid feed for selected tools."""
    names = sorted({_clean(name) for name in tool_names if _clean(name)})
    if not names:
        return {"tools": 0, "authorEvidence": 0, "maintainerEvidence": 0}
    canonical = set(
        s.execute(select(CanonicalToolCache.tool_name).where(CanonicalToolCache.tool_name.in_(names))).scalars()
    )
    rows = s.execute(
        select(ToolinfoSourceItem, ToolinfoSource)
        .join(ToolinfoSource, ToolinfoSourceItem.source_id == ToolinfoSource.id)
        .where(ToolinfoSourceItem.tool_name.in_(names), ToolinfoSource.valid.is_(True))
    ).all()
    by_tool: dict[str, list[tuple[ToolinfoSourceItem, ToolinfoSource]]] = defaultdict(list)
    for item, source in rows:
        by_tool[item.tool_name].append((item, source))
    source_ids = {source.id for _item, source in rows}
    bindings = {
        (row.source_id, row.normalized_label): row
        for row in s.execute(
            select(ToolinfoAuthorBinding).where(
                ToolinfoAuthorBinding.source_id.in_(source_ids or {-1}),
                ToolinfoAuthorBinding.withdrawn_at.is_(None),
            )
        ).scalars()
    }
    members_by_project = _verified_members_by_project(s)
    person_ids = {row.person_id for row in bindings.values() if row.person_id is not None} | {
        binding.person_id
        for members in members_by_project.values()
        for _account, binding in members
        if binding.person_id is not None
    }
    identities = {person_id: _person_identity(s, person_id) for person_id in person_ids}
    display_names = {
        person.id: person.display_name
        for person in s.execute(select(Person).where(Person.id.in_(person_ids or {-1}))).scalars()
    }
    author_count = maintainer_count = 0
    for tool_name in names:
        authors, maintainers = (
            _observations_for_tool(
                tool_name,
                by_tool.get(tool_name, []),
                bindings,
                members_by_project,
                identities,
                display_names,
            )
            if tool_name in canonical
            else ([], [])
        )
        author_count += len(people_index.replace_source_evidence(s, tool_name, SOURCE_AUTHOR_ATTESTATION, authors))
        maintainer_count += len(
            people_index.replace_source_evidence(s, tool_name, SOURCE_TARGET_MEMBERSHIP, maintainers)
        )
    return {"tools": len(names), "authorEvidence": author_count, "maintainerEvidence": maintainer_count}


def refresh_source_ids(
    s: Session,
    source_ids: list[int],
    *,
    affected_tool_names: list[str] | None = None,
) -> dict[str, int]:
    """Resolve changed feeds, update bindings, and project all affected tools."""
    ids = sorted({int(source_id) for source_id in source_ids})
    run = PersonReconciliationRun(mode=RECONCILIATION_RUN_MODE, status="running", started_at=utcnow())
    s.add(run)
    s.flush()
    totals = {
        "sources": 0,
        "verified": 0,
        "resolved": 0,
        "unresolved": 0,
        "conflicts": 0,
        "tools": 0,
        "authorEvidence": 0,
        "maintainerEvidence": 0,
    }
    affected_names = {_clean(name) for name in (affected_tool_names or []) if _clean(name)} | set(
        s.execute(select(ToolinfoSourceItem.tool_name).where(ToolinfoSourceItem.source_id.in_(ids or {-1}))).scalars()
    )
    handle_index = _verified_handle_index(s)
    for source in s.execute(select(ToolinfoSource).where(ToolinfoSource.id.in_(ids or {-1}))).scalars():
        items = list(s.execute(select(ToolinfoSourceItem).where(ToolinfoSourceItem.source_id == source.id)).scalars())
        attestation = _resolve_attestation(s, source)
        if attestation.status == STATUS_CONFLICT:
            controller_ids = {
                int(person_id)
                for person_id in attestation.evidence.get("controllerPersonIds", [])
                if str(person_id).isdigit()
            }
            _record_conflict(
                s,
                run.id,
                source,
                "<source-controller>",
                controller_ids,
                attestation.method,
            )
            totals["conflicts"] += 1
        binding_stats = _refresh_bindings(s, source, attestation, items, run.id, handle_index)
        totals["sources"] += 1
        for key, value in binding_stats.items():
            totals[key] += value
    projection = refresh_tool_names(s, sorted(affected_names))
    totals.update(projection)
    run.status = "completed"
    run.completed_at = utcnow()
    run.summary = totals
    return totals


def refresh_all(s: Session) -> dict[str, int]:
    """Re-evaluate every indexed source after identity or rule changes."""
    return refresh_source_ids(s, list(s.execute(select(ToolinfoSource.id)).scalars()))


def refresh_full(s: Session) -> dict[str, int]:
    """Run a complete audit and publish the rules version only after success."""
    totals = refresh_all(s)
    rules = s.get(ApiCacheMeta, RULES_META_KEY)
    if rules is None:
        s.add(ApiCacheMeta(key=RULES_META_KEY, value=RULES_VERSION))
    else:
        rules.value = RULES_VERSION
        rules.updated_at = utcnow()
    totals["fullAudit"] = 1
    return totals


def refresh_full_batched(*, batch_size: int = FULL_AUDIT_BATCH_SIZE) -> dict[str, int]:
    """Audit every source in bounded transactions under one writer lease.

    A monolithic audit can hold source and relationship rows for several
    minutes. Production has minute-level incremental writers, so one collision
    can otherwise exhaust MariaDB's lock wait timeout and roll back the whole
    audit. Each batch is independently atomic and retryable; the rules marker
    is published only after every batch succeeds.
    """
    size = max(1, int(batch_size))
    with db.advisory_lock(SOURCE_WRITER_LOCK, timeout_seconds=120) as acquired:
        if not acquired:
            raise SourceAttestationBusyError
        with db.session_scope() as session:
            source_ids = list(session.execute(select(ToolinfoSource.id).order_by(ToolinfoSource.id)).scalars())
            tool_names = set(session.execute(select(ToolinfoSourceItem.tool_name).distinct()).scalars())

        totals = {
            "sources": 0,
            "verified": 0,
            "resolved": 0,
            "unresolved": 0,
            "conflicts": 0,
            "tools": 0,
            "authorEvidence": 0,
            "maintainerEvidence": 0,
        }
        batches = [source_ids[offset : offset + size] for offset in range(0, len(source_ids), size)]
        for source_batch in batches:

            def refresh_batch(batch: tuple[int, ...] = tuple(source_batch)) -> dict[str, int]:
                with db.session_scope() as session:
                    return refresh_source_ids(session, list(batch))

            batch_totals = db.run_with_lock_retry(refresh_batch)
            for key in totals:
                totals[key] += batch_totals[key]

        with db.session_scope() as session:
            rules = session.get(ApiCacheMeta, RULES_META_KEY)
            if rules is None:
                session.add(ApiCacheMeta(key=RULES_META_KEY, value=RULES_VERSION))
            else:
                rules.value = RULES_VERSION
                rules.updated_at = utcnow()
            # Source batches can share tool names. Report the final active
            # projection, not the sum of repeated per-batch replacements.
            totals["tools"] = len(tool_names)
            totals["authorEvidence"] = (
                session.scalar(
                    select(func.count())
                    .select_from(ToolRelationshipEvidence)
                    .where(
                        ToolRelationshipEvidence.tool_name.in_(tool_names or {"<none>"}),
                        ToolRelationshipEvidence.source == SOURCE_AUTHOR_ATTESTATION,
                        ToolRelationshipEvidence.withdrawn_at.is_(None),
                    )
                )
                or 0
            )
            totals["maintainerEvidence"] = (
                session.scalar(
                    select(func.count())
                    .select_from(ToolRelationshipEvidence)
                    .where(
                        ToolRelationshipEvidence.tool_name.in_(tool_names or {"<none>"}),
                        ToolRelationshipEvidence.source == SOURCE_TARGET_MEMBERSHIP,
                        ToolRelationshipEvidence.withdrawn_at.is_(None),
                    )
                )
                or 0
            )
        totals["batches"] = len(batches)
        totals["fullAudit"] = 1
        return totals


def _content_changed_source_ids(s: Session) -> set[int]:
    """Return sources whose latest complete feed is newer than its projection."""
    attestations = {row.source_id: row for row in s.execute(select(ToolinfoSourceAttestation)).scalars()}
    ranked = select(
        ToolinfoSourceGeneration.source_id.label("source_id"),
        ToolinfoSourceGeneration.content_hash.label("content_hash"),
        ToolinfoSourceGeneration.fetched_at.label("fetched_at"),
        func.row_number()
        .over(
            partition_by=ToolinfoSourceGeneration.source_id,
            order_by=(ToolinfoSourceGeneration.fetched_at.desc(), ToolinfoSourceGeneration.id.desc()),
        )
        .label("generation_rank"),
    ).subquery()
    generations: dict[int, list[Any]] = defaultdict(list)
    for row in s.execute(
        select(ranked.c.source_id, ranked.c.content_hash, ranked.c.fetched_at)
        .where(ranked.c.generation_rank <= GENERATION_COMPARISON_DEPTH)
        .order_by(ranked.c.source_id, ranked.c.generation_rank)
    ):
        generations[int(row.source_id)].append(row)
    changed: set[int] = set()
    for source_id in s.execute(select(ToolinfoSource.id)).scalars():
        recent = generations.get(source_id, [])
        attestation = attestations.get(source_id)
        if attestation is None or (
            recent
            and recent[0].fetched_at > attestation.checked_at
            and (len(recent) == 1 or recent[0].content_hash != recent[1].content_hash)
        ):
            changed.add(source_id)
    return changed


def _identity_changed_source_ids(s: Session, changed_since: Any | None) -> set[int]:  # noqa: ANN401
    if changed_since is None:
        return set()
    identifiers = list(
        s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.updated_at >= changed_since,
                PersonIdentifier.is_current.is_(True),
            )
        ).scalars()
    )
    person_ids = {row.person_id for row in identifiers}
    labels = {row.normalized_value for row in identifiers if row.normalized_value}
    binding_person_ids = set(
        s.execute(
            select(PersonAccountBinding.person_id).where(
                PersonAccountBinding.updated_at >= changed_since,
                PersonAccountBinding.person_id.is_not(None),
            )
        ).scalars()
    )
    person_ids.update(int(person_id) for person_id in binding_person_ids if person_id is not None)
    source_ids = set(
        s.execute(
            select(ToolinfoAuthorBinding.source_id).where(
                ToolinfoAuthorBinding.normalized_label.in_(labels or {"<none>"})
            )
        ).scalars()
    )
    source_ids.update(
        source.id
        for source in s.execute(select(ToolinfoSource)).scalars()
        if source.created_by_username.casefold() in labels
    )
    source_ids.update(
        s.execute(
            select(ToolinfoSourceAttestation.source_id).where(
                ToolinfoSourceAttestation.controller_person_id.in_(person_ids or {-1})
            )
        ).scalars()
    )
    return source_ids


def refresh_incremental(s: Session, *, identity_changed_since: Any | None = None) -> dict[str, int]:  # noqa: ANN401
    """Refresh only changed feeds and sources affected by new stable identities."""
    rules = s.get(ApiCacheMeta, RULES_META_KEY)
    if rules is None or rules.value != RULES_VERSION:
        return refresh_full(s)
    source_ids = _content_changed_source_ids(s) | _identity_changed_source_ids(s, identity_changed_since)
    if not source_ids:
        return {
            "sources": 0,
            "verified": 0,
            "resolved": 0,
            "unresolved": 0,
            "conflicts": 0,
            "tools": 0,
            "authorEvidence": 0,
            "maintainerEvidence": 0,
            "fullAudit": 0,
        }
    totals = refresh_source_ids(s, sorted(source_ids))
    totals["fullAudit"] = 0
    return totals
