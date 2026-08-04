# SPDX-License-Identifier: GPL-3.0-or-later
"""Relationship-evidence ingestion and compatibility health summaries.

The module name is retained for internal callers, but the former maintainer
edge and username-rollup projections no longer exist. Toolhub catalog metadata
is recorded as canonical upstream evidence; Evolved claims and Toolsadmin are
complementary evidence and never grant Toolhub permissions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from backend import people_index
from backend.models import (
    PersonActivitySummary,
    ToolAuthorClaim,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    User,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_FAILED,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_STALE,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_UNVERIFIED,
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_CATALOG_ACTOR,
    PERSON_REL_MAINTAINER,
    PERSON_REL_RECORD_OWNER,
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
    clean_author_claim_method,
    clean_author_claim_status,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from backend.author_claims import ToolsadminMaintainer

SOURCE_AUTHOR_CLAIM = "evolved_author_claim"
SOURCE_TOOLHUB_AUTHOR = "toolhub_author_metadata"
SOURCE_TOOLHUB_ACTOR = "toolhub_catalog_actor"
SOURCE_TOOLFORGE_TOOLSADMIN = "toolforge_toolsadmin"
METHOD_TOOLHUB_AUTHOR = "toolhub_author_metadata"
METHOD_TOOLHUB_CREATED_BY = "toolhub_created_by"
METHOD_TOOLHUB_MODIFIED_BY = "toolhub_modified_by"
VERIFIED_CONFIDENCE_MIN = 70
VERIFIED_STATUS_CONFIDENCE_MIN = 85
CLAIM_RANK_MIN = datetime.min.replace(tzinfo=UTC).replace(tzinfo=None)

CLAIM_CONFIDENCE = {
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER: 95,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS: 90,
    AUTHOR_CLAIM_SIGNED_TOOLINFO: 88,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL: 82,
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME: 35,
}
STATUS_MULTIPLIER = {
    AUTHOR_CLAIM_VERIFIED: 1.0,
    AUTHOR_CLAIM_STALE: 0.65,
    AUTHOR_CLAIM_UNVERIFIED: 0.55,
    AUTHOR_CLAIM_FAILED: 0.0,
}


def clean_text(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - untrusted source data
    return str(value or "").strip()[:limit]


def _claim_status(row: ToolAuthorClaim) -> str:
    status = clean_author_claim_status(row.verification_status)
    if status == AUTHOR_CLAIM_VERIFIED and row.expires_at is not None and row.expires_at <= utcnow():
        return AUTHOR_CLAIM_STALE
    return status


def _claim_confidence(row: ToolAuthorClaim) -> int:
    method = clean_author_claim_method(row.verification_method)
    return round(CLAIM_CONFIDENCE.get(method, 20) * STATUS_MULTIPLIER.get(_claim_status(row), 0.5))


def _claim_identity(row: ToolAuthorClaim) -> tuple[str, str, str]:
    return (
        clean_text(row.tool_name),
        f"user:{row.user_id}" if row.user_id is not None else f"username:{clean_text(row.toolhub_username).casefold()}",
        clean_author_claim_method(row.verification_method),
    )


def _best_claim_rows(rows: list[ToolAuthorClaim]) -> list[ToolAuthorClaim]:
    best: dict[tuple[str, str, str], ToolAuthorClaim] = {}
    for row in rows:
        identity = _claim_identity(row)
        current = best.get(identity)
        rank = (_claim_confidence(row), row.checked_at or CLAIM_RANK_MIN)
        current_rank = (_claim_confidence(current), current.checked_at or CLAIM_RANK_MIN) if current else None
        if current_rank is None or rank > current_rank:
            best[identity] = row
    return [best[key] for key in sorted(best)]


def _claim_role(row: ToolAuthorClaim) -> str:
    method = clean_author_claim_method(row.verification_method)
    if method == AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS:
        return PERSON_REL_RECORD_OWNER
    if method == AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME:
        return PERSON_REL_AUTHOR
    return PERSON_REL_MAINTAINER


def sync_author_claim_edges(
    s: Session,
    *,
    tool_names: list[str] | None = None,
    usernames: list[str] | None = None,
    user_ids: list[int] | None = None,
) -> list[ToolRelationshipEvidence]:
    """Replace Evolved claim evidence for the requested tools."""
    query = select(ToolAuthorClaim).where(ToolAuthorClaim.revoked_at.is_(None))
    if tool_names:
        query = query.where(ToolAuthorClaim.tool_name.in_(tool_names))
    if usernames:
        query = query.where(ToolAuthorClaim.toolhub_username.in_(usernames))
    if user_ids:
        query = query.where(ToolAuthorClaim.user_id.in_(user_ids))
    claims = _best_claim_rows(list(s.execute(query).scalars()))
    users_by_id = {
        user.id: user
        for user in s.execute(
            select(User).where(User.id.in_({claim.user_id for claim in claims if claim.user_id}))
        ).scalars()
    }
    for username in {clean_text(claim.toolhub_username) for claim in claims if claim.user_id is None}:
        for user in s.execute(select(User).where(func.lower(User.username) == username.casefold())).scalars():
            claim_rows = [
                claim
                for claim in claims
                if claim.user_id is None and clean_text(claim.toolhub_username).casefold() == username.casefold()
            ]
            for claim in claim_rows:
                claim.user_id = user.id
                claim.toolhub_username = user.username
            users_by_id[user.id] = user
    for user in users_by_id.values():
        people_index.link_user(s, user)
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        method = clean_author_claim_method(claim.verification_method)
        user = users_by_id.get(claim.user_id) if claim.user_id is not None else None
        by_tool.setdefault(clean_text(claim.tool_name), []).append(
            {
                "display_name": clean_text((user.username if user else claim.toolhub_username) or claim.author_name),
                "toolhub_user_id": clean_text(user.wm_sub) if user else "",
                "toolhub_username": clean_text(user.username if user else claim.toolhub_username),
                "relationship_type": _claim_role(claim),
                "method": method,
                "evidence_key": clean_text(claim.author_name),
                "verification_status": _claim_status(claim),
                "confidence": _claim_confidence(claim),
                "evidence_url": claim.evidence_url,
                "evidence_payload": claim.evidence_payload,
                "checked_at": claim.checked_at,
                "expires_at": claim.expires_at,
                "last_error": claim.last_error,
            }
        )
    affected = {clean_text(name) for name in (tool_names or []) if clean_text(name)} | set(by_tool)
    rows: list[ToolRelationshipEvidence] = []
    for tool_name in sorted(affected):
        rows.extend(people_index.replace_source_evidence(s, tool_name, SOURCE_AUTHOR_CLAIM, by_tool.get(tool_name, [])))
    return rows


def replace_toolforge_maintainer_edges(
    s: Session,
    tool_name: str,
    pages: list[tuple[str, list[ToolsadminMaintainer], str]],
    *,
    checked_at: Any = None,  # noqa: ANN401 - SQLAlchemy datetime passthrough
    expires_at: Any = None,  # noqa: ANN401 - SQLAlchemy datetime passthrough
) -> list[ToolRelationshipEvidence]:
    """Replace Toolsadmin operational-maintainer evidence for one tool."""
    observations = []
    for toolforge_name, maintainers, evidence_url in pages:
        for maintainer in maintainers:
            display = clean_text(maintainer.display_name)
            if not display:
                continue
            observations.append(
                {
                    "display_name": display,
                    "wiki_username": clean_text(maintainer.username),
                    "relationship_type": PERSON_REL_MAINTAINER,
                    "method": AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    "evidence_key": clean_text(toolforge_name),
                    "verification_status": AUTHOR_CLAIM_VERIFIED,
                    "confidence": CLAIM_CONFIDENCE[AUTHOR_CLAIM_TOOLFORGE_MAINTAINER],
                    "evidence_url": evidence_url,
                    "evidence_payload": {
                        "toolforgeToolName": toolforge_name,
                        "profileUsername": clean_text(maintainer.username),
                    },
                    "checked_at": checked_at,
                    "expires_at": expires_at,
                }
            )
    return people_index.replace_source_evidence(s, tool_name, SOURCE_TOOLFORGE_TOOLSADMIN, observations)


def _toolhub_observations(tool: dict[str, Any]) -> list[dict[str, Any]]:
    raw_authors = tool.get("author")
    authors = raw_authors if isinstance(raw_authors, list) else [raw_authors]
    observations: list[dict[str, Any]] = []
    for index, author in enumerate(authors):
        if isinstance(author, dict):
            display = clean_text(author.get("name") or author.get("developer_username") or author.get("wiki_username"))
            toolhub_username = clean_text(author.get("developer_username"))
            wiki_username = clean_text(author.get("wiki_username"))
        else:
            display = clean_text(author)
            toolhub_username = ""
            wiki_username = ""
        if display:
            observations.append(
                {
                    "display_name": display,
                    "source": SOURCE_TOOLHUB_AUTHOR,
                    "toolhub_username": toolhub_username,
                    "wiki_username": wiki_username,
                    "relationship_type": PERSON_REL_AUTHOR,
                    "method": METHOD_TOOLHUB_AUTHOR,
                    "evidence_key": str(index),
                    "verification_status": AUTHOR_CLAIM_UNVERIFIED,
                    "confidence": 45,
                    "toolhub_canonical": True,
                    "evidence_payload": {"toolhubField": "author"},
                }
            )
    for field, method in (("created_by", METHOD_TOOLHUB_CREATED_BY), ("modified_by", METHOD_TOOLHUB_MODIFIED_BY)):
        actor = tool.get(field)
        if not isinstance(actor, dict):
            continue
        username = clean_text(actor.get("username"))
        user_id = clean_text(actor.get("id"), 64)
        if username or user_id:
            observations.append(
                {
                    "display_name": username,
                    "source": SOURCE_TOOLHUB_ACTOR,
                    "toolhub_user_id": user_id,
                    "toolhub_username": username,
                    # Catalog actors are observations, not ownership grants.
                    "relationship_type": PERSON_REL_CATALOG_ACTOR,
                    "method": method,
                    "evidence_key": field,
                    "verification_status": AUTHOR_CLAIM_UNVERIFIED,
                    "confidence": 55,
                    "toolhub_canonical": True,
                    "evidence_payload": {"toolhubField": field},
                }
            )
    return observations


def replace_toolhub_metadata_edges(s: Session, tool_name: str, tool: dict[str, Any]) -> list[ToolRelationshipEvidence]:
    """Project canonical Toolhub author and actor fields into evidence."""
    observations = _toolhub_observations(tool)
    rows = people_index.replace_source_evidence(
        s,
        tool_name,
        SOURCE_TOOLHUB_AUTHOR,
        [row for row in observations if row["source"] == SOURCE_TOOLHUB_AUTHOR],
    )
    rows.extend(
        people_index.replace_source_evidence(
            s,
            tool_name,
            SOURCE_TOOLHUB_ACTOR,
            [row for row in observations if row["source"] == SOURCE_TOOLHUB_ACTOR],
        )
    )
    return rows


def activity_payload(row: PersonActivitySummary | None) -> dict[str, Any]:
    return people_index.activity_payload(row)


def _summary_status(relationships: list[ToolPersonRelationship]) -> str:
    if not relationships:
        return "unknown"
    verified = [row.confidence for row in relationships if row.verification_status == AUTHOR_CLAIM_VERIFIED]
    best = max(verified or [row.confidence for row in relationships])
    if verified and best >= VERIFIED_STATUS_CONFIDENCE_MIN:
        return "verified"
    return "probable" if best >= VERIFIED_CONFIDENCE_MIN else "candidate"


def public_tool_summary(s: Session, tool_name: str) -> dict[str, Any]:
    """Return the normalized people summary plus health-scoring aggregates."""
    summary = people_index.public_people_summary(s, tool_name)
    relationships = list(
        s.execute(
            select(ToolPersonRelationship).where(ToolPersonRelationship.tool_name == clean_text(tool_name))
        ).scalars()
    )
    people = summary["people"]
    activity_statuses = [str(item.get("activity", {}).get("status") or "unknown") for item in people]
    summary.update(
        {
            "status": _summary_status(relationships),
            "bestConfidence": max((row.confidence for row in relationships), default=0),
            "healthCounts": {
                "people": len(people),
                "maintainers": summary["counts"].get(PERSON_REL_MAINTAINER, 0),
                "verifiedPeople": len(
                    {row.person_id for row in relationships if row.verification_status == AUTHOR_CLAIM_VERIFIED}
                ),
                "activePeople": sum(status in {"active", "quiet"} for status in activity_statuses),
                "evidence": sum(row.evidence_count for row in relationships),
            },
            "publicDataPolicy": {
                "catalogAuthority": "toolhub",
                "relationshipProjection": "toolhub-evolved",
                "evidencePayload": "private",
            },
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
        }
    )
    return summary
