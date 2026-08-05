# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/user/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from flask import Blueprint, Response, jsonify, session
from sqlalchemy import delete, func, select

from backend import (
    authz,
    db,
    maintainer_index,
    people_index,
)
from backend import v1_common as common
from backend.models import (
    ActivityRow,
    CrawlerUrl,
    Favorite,
    Person,
    PersonActivitySummary,
    PersonProfile,
    SourceAnalysisReport,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolEvent,
    ToolHealthTarget,
    ToolhubToken,
    ToolinfoControlChallenge,
    ToolList,
    ToolMedia,
    ToolOverlay,
    ToolRecord,
    ToolRelationshipEvidence,
    ToolThanks,
    User,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard
from backend.toolinfo_control import (
    challenge_payload,
)

v1_user_bp = Blueprint("v1_user", __name__)


@v1_user_bp.route("/v1/user/")
def v1_user() -> Response:
    """Who am I? Adds the CSRF token the write endpoints require."""
    uid = current_user_id()
    if uid is None:
        return jsonify({"authenticated": False})
    with db.session_scope() as s:
        user = s.get(User, uid)
        if user is None:  # pragma: no cover - delete-mid-request race; see _current_policy_user
            session.clear()
            return jsonify({"authenticated": False})
        role = authz.user_role(user)
        official_writes = s.get(ToolhubToken, uid) is not None
        return jsonify(
            {
                "authenticated": True,
                "username": user.username,
                "csrf": session.get("csrf", ""),
                "officialWrites": official_writes,
                "evolvedRole": role,
                "evolvedRoleLabel": authz.role_label(role),
                "evolvedPermissions": authz.role_permissions(role),
            }
        )


@v1_user_bp.route("/v1/user/export/")
@login_required
def v1_user_export() -> Response:
    """Export the caller's Evolved-owned data; official Toolhub data is not copied."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    username = user.username
    with db.session_scope() as s:
        author_claims = [
            common.claim_payload(row)
            for row in s.execute(
                select(ToolAuthorClaim)
                .where(common.author_claim_owned_by(user))
                .order_by(
                    ToolAuthorClaim.tool_name,
                    ToolAuthorClaim.author_name,
                    ToolAuthorClaim.verification_method,
                )
            ).scalars()
        ]
        author_keys = [
            common.author_key_payload(row)
            for row in s.execute(
                select(ToolAuthorKey)
                .where(common.author_key_owned_by(user))
                .order_by(ToolAuthorKey.created_at, ToolAuthorKey.id)
            ).scalars()
        ]
        ownership_challenges = [
            challenge_payload(row)
            for row in s.execute(
                select(ToolinfoControlChallenge)
                .where(ToolinfoControlChallenge.user_id == uid)
                .order_by(ToolinfoControlChallenge.created_at, ToolinfoControlChallenge.id)
            ).scalars()
        ]
        source_analysis_reports = [
            common.source_analysis_payload(row)
            for row in s.execute(
                select(SourceAnalysisReport)
                .where(SourceAnalysisReport.user_id == uid)
                .order_by(SourceAnalysisReport.created_at, SourceAnalysisReport.id)
            ).scalars()
        ]
        person = s.get(Person, user.person_id) if user.person_id is not None else None
        relationship_evidence = [
            {
                "toolName": row.tool_name,
                "relationshipType": row.relationship_type,
                "source": row.source,
                "method": row.method,
                "verificationStatus": row.verification_status,
                "confidence": row.confidence,
                "checkedAt": common.iso(row.checked_at),
                "expiresAt": common.iso(row.expires_at),
            }
            for row in s.execute(
                select(ToolRelationshipEvidence)
                .where(
                    ToolRelationshipEvidence.person_id == (person.id if person is not None else -1),
                    ToolRelationshipEvidence.source == maintainer_index.SOURCE_AUTHOR_CLAIM,
                    ToolRelationshipEvidence.withdrawn_at.is_(None),
                )
                .order_by(ToolRelationshipEvidence.tool_name, ToolRelationshipEvidence.method)
            ).scalars()
        ]
        contribution_activity = people_index.activity_payload(
            s.get(PersonActivitySummary, person.id) if person is not None else None
        )
        profile = s.get(PersonProfile, person.id) if person is not None else None
    return jsonify(
        {
            "exportedAt": common.iso(utcnow()),
            "user": {"username": username},
            "overlay": common.assemble_overlay(uid),
            "authorClaims": author_claims,
            "authorKeys": author_keys,
            "ownershipChallenges": ownership_challenges,
            "person": {"id": person.public_id, "displayName": person.display_name} if person is not None else None,
            "profile": common.profile_payload(profile, person) if profile is not None and person is not None else None,
            "contributionActivity": contribution_activity,
            "relationshipEvidence": relationship_evidence,
            "sourceAnalysisReports": source_analysis_reports,
        }
    )


@v1_user_bp.route("/v1/user/evolved-data/", methods=["DELETE"])
@write_guard
def v1_user_delete_evolved_data() -> Response:
    """Delete the caller's local Evolved data without touching official Toolhub."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    deleted: dict[str, int] = {}
    with db.session_scope() as s:
        for key, model in {
            "favorites": Favorite,
            "lists": ToolList,
            "toolNew": ToolRecord,
            "toolOverlays": ToolOverlay,
            "activity": ActivityRow,
            "crawlerUrls": CrawlerUrl,
            "toolEvents": ToolEvent,
            "thanks": ToolThanks,
            "media": ToolMedia,
            "sourceAnalysisReports": SourceAnalysisReport,
            "ownershipChallenges": ToolinfoControlChallenge,
        }.items():
            count = s.execute(select(func.count()).select_from(model).where(model.user_id == uid)).scalar_one()
            deleted[key] = int(count)
            s.execute(delete(model).where(model.user_id == uid))
        health_count = s.execute(
            select(func.count()).select_from(ToolHealthTarget).where(ToolHealthTarget.created_by_user_id == uid)
        ).scalar_one()
        deleted["healthTargets"] = int(health_count)
        s.execute(delete(ToolHealthTarget).where(ToolHealthTarget.created_by_user_id == uid))
        author_claim_owner = common.author_claim_owned_by(user)
        author_claim_count = s.execute(
            select(func.count()).select_from(ToolAuthorClaim).where(author_claim_owner)
        ).scalar_one()
        deleted["authorClaims"] = int(author_claim_count)
        s.execute(delete(ToolAuthorClaim).where(author_claim_owner))
        author_key_owner = common.author_key_owned_by(user)
        author_key_count = s.execute(
            select(func.count()).select_from(ToolAuthorKey).where(author_key_owner)
        ).scalar_one()
        deleted["authorKeys"] = int(author_key_count)
        s.execute(delete(ToolAuthorKey).where(author_key_owner))
        person_id = user.person_id
        affected_tools = {
            row[0]
            for row in s.execute(
                select(ToolRelationshipEvidence.tool_name).where(
                    ToolRelationshipEvidence.person_id == (person_id if person_id is not None else -1),
                    ToolRelationshipEvidence.source == maintainer_index.SOURCE_AUTHOR_CLAIM,
                )
            ).all()
        }
        evidence_count = s.execute(
            select(func.count())
            .select_from(ToolRelationshipEvidence)
            .where(
                ToolRelationshipEvidence.person_id == (person_id if person_id is not None else -1),
                ToolRelationshipEvidence.source == maintainer_index.SOURCE_AUTHOR_CLAIM,
            )
        ).scalar_one()
        deleted["relationshipEvidence"] = int(evidence_count)
        s.execute(
            delete(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.person_id == (person_id if person_id is not None else -1),
                ToolRelationshipEvidence.source == maintainer_index.SOURCE_AUTHOR_CLAIM,
            )
        )
        profile_count = 0
        if person_id is not None:
            profile_count = int(
                s.execute(
                    select(func.count()).select_from(PersonProfile).where(PersonProfile.person_id == person_id)
                ).scalar_one()
            )
            s.execute(delete(PersonProfile).where(PersonProfile.person_id == person_id))
        deleted["profile"] = profile_count
        for tool_name in sorted(affected_tools):
            people_index.resolve_tool_relationships(s, tool_name)
        if person_id is not None:
            people_index.refresh_activity_summaries(s, person_ids={person_id})
    return jsonify({"ok": True, "deleted": deleted})
