# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed-in account reads backed by the canonical people relationship graph."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import select

from backend import authz, db, people_index, tool_summaries, toolinfo_discovery, toolinfo_sources
from backend import v1_common as common
from backend.models import (
    CanonicalToolCache,
    PersonAccountBinding,
    PersonProfile,
    ToolAuthorClaim,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolPersonRelationship,
    User,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard
from backend.sync import AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME, AUTHOR_CLAIM_TOOLFORGE_MAINTAINER

v1_me_bp = Blueprint("v1_me", __name__)


@v1_me_bp.route("/v1/me/claims/")
@login_required
def v1_me_claims() -> Response:
    """List relationship-claim workflow rows owned by the signed-in account."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees a session
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as session:
        rows = list(
            session.execute(
                select(ToolAuthorClaim)
                .where(
                    common.author_claim_owned_by(user),
                    ToolAuthorClaim.requested_relationship.in_(people_index.PUBLIC_ROLES),
                )
                .order_by(ToolAuthorClaim.updated_at.desc(), ToolAuthorClaim.id.desc())
            ).scalars()
        )
        return jsonify({"claims": [common.claim_payload(row) for row in rows]})


def _relationship_claim(relationship: ToolPersonRelationship) -> dict[str, Any]:
    """Adapt one resolved graph edge to the account-workbench claim contract."""
    method = (
        AUTHOR_CLAIM_TOOLFORGE_MAINTAINER
        if relationship.relationship_type == "maintainer"
        else AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME
    )
    return {
        "toolName": relationship.tool_name,
        "verificationStatus": relationship.verification_status,
        "verificationMethod": method,
        "requestedRelationship": relationship.relationship_type,
        "isVerified": relationship.verification_status == "verified",
        "confidence": relationship.confidence,
        "evidenceCount": relationship.evidence_count,
    }


def _canonical_account_tools(user: User) -> dict[str, Any]:
    """Return exactly the relationship graph used by public person profiles."""
    with db.session_scope() as session:
        stored_user = session.get(User, user.id)
        if stored_user is None:
            return {"username": user.username, "verified": [], "possible": [], "errors": []}
        person = people_index.link_user(session, stored_user)
        relationships = list(
            session.execute(
                select(ToolPersonRelationship)
                .where(
                    ToolPersonRelationship.person_id == person.id,
                    ToolPersonRelationship.relationship_type.in_(people_index.PUBLIC_ROLES),
                )
                .order_by(ToolPersonRelationship.tool_name, ToolPersonRelationship.relationship_type)
            ).scalars()
        )
        names = sorted({row.tool_name for row in relationships})
        records = {
            row.tool_name: row.record
            for row in session.execute(
                select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(names or {""}))
            ).scalars()
            if isinstance(row.record, dict)
        }
        stored_claims = list(
            session.execute(
                select(ToolAuthorClaim).where(
                    common.author_claim_owned_by(stored_user),
                    ToolAuthorClaim.revoked_at.is_(None),
                    ToolAuthorClaim.tool_name.in_(names or {""}),
                    ToolAuthorClaim.requested_relationship.in_(people_index.PUBLIC_ROLES),
                )
            ).scalars()
        )
        claims_by_tool: dict[str, list[dict[str, Any]]] = {}
        for claim in stored_claims:
            claims_by_tool.setdefault(claim.tool_name, []).append(common.claim_payload(claim))
        relationships_by_tool: dict[str, list[ToolPersonRelationship]] = {}
        for relationship in relationships:
            relationships_by_tool.setdefault(relationship.tool_name, []).append(relationship)
        candidates = {name: {"tool": records[name]} for name in names if name in records}
        discoveries = toolinfo_discovery.ensure_pending_for_candidates(candidates)
        sources = toolinfo_sources.sources_for_tools(names)
        verified: list[dict[str, Any]] = []
        possible: list[dict[str, Any]] = []
        for name in names:
            record = records.get(name)
            if record is None:
                continue
            edges = relationships_by_tool[name]
            edge_claims = [_relationship_claim(edge) for edge in edges]
            item = {
                "tool": record,
                "matchedAuthorNames": [person.display_name],
                "searchTerms": ["canonical-relationship-graph"],
                "claims": [*claims_by_tool.get(name, []), *edge_claims],
                "relationships": edge_claims,
                "toolinfoDiscovery": discoveries.get(name, {"status": "pending"}),
                "toolinfoSource": sources.get(name),
            }
            bucket = verified if any(edge.verification_status == "verified" for edge in edges) else possible
            bucket.append(item)
        binding = session.execute(
            select(PersonAccountBinding).where(
                PersonAccountBinding.person_id == person.id,
                PersonAccountBinding.provider == "toolforge",
                PersonAccountBinding.status == "verified",
                PersonAccountBinding.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        toolforge_names: list[str] = []
        if binding is not None and session.get(ToolforgeAccountProjection, binding.external_id) is not None:
            toolforge_names = list(
                session.execute(
                    select(ToolforgeMembershipProjection.tool_name)
                    .where(ToolforgeMembershipProjection.uid_number == binding.external_id)
                    .order_by(ToolforgeMembershipProjection.tool_name)
                ).scalars()
            )
        return {
            "username": stored_user.username,
            "personId": person.public_id,
            "person": {"id": person.public_id, "displayName": person.display_name},
            "searchTerms": ["canonical-relationship-graph"],
            "toolforgeToolNames": toolforge_names,
            "counts": {"verified": len(verified), "possible": len(possible)},
            "verified": verified,
            "possible": possible,
            "errors": [],
        }


def _tool_summaries(payload: dict[str, Any]) -> dict[str, Any]:
    names = [
        item["tool"]["name"]
        for bucket in ("verified", "possible")
        for item in payload.get(bucket, [])
        if isinstance(item, dict) and isinstance(item.get("tool"), dict) and item["tool"].get("name")
    ][: common.ME_TOOLS_SUMMARY_LIMIT]
    if not names:
        return {}
    return tool_summaries.summaries_for(
        names,
        common.build_local_tool_summary,
        refresh_stale=False,
        view=tool_summaries.VIEW_CARD,
    ).results


@v1_me_bp.route("/v1/me/tools/")
@login_required
def v1_me_tools() -> Response:
    """Read account tools from the canonical relationship graph without fan-out."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees a session
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    payload = _canonical_account_tools(user)
    response = jsonify({**payload, "cache": {"status": "canonical"}, "summaries": _tool_summaries(payload)})
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _profile_url(value: Any) -> str:  # noqa: ANN401 - JSON input
    clean = str(value or "").strip()[:2000]
    if not clean:
        return ""
    parsed = urlparse(clean)
    return clean if parsed.scheme == "https" and parsed.netloc else ""


@v1_me_bp.route("/v1/me/profile/")
@login_required
def v1_me_profile_get() -> Response:
    """Read Evolved-owned profile content for the signed-in person."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees a session
    with db.session_scope() as session:
        user = session.get(User, uid)
        if user is None:
            return common.deny(common.HTTP_UNAUTHORIZED, "sign in required")
        person = people_index.link_user(session, user)
        return jsonify({"profile": common.profile_payload(session.get(PersonProfile, person.id), person)})


@v1_me_bp.route("/v1/me/profile/", methods=["PUT"])
@write_guard
def v1_me_profile_put() -> Response:
    """Update Evolved-owned profile content for the signed-in person."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - write_guard guarantees a session
    with db.session_scope() as session:
        user = session.get(User, uid)
        if user is None:
            return common.deny(common.HTTP_UNAUTHORIZED, "sign in required")
        person = people_index.link_user(session, user)
        profile = session.get(PersonProfile, person.id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return common.bad("JSON object required")
        if profile is None:
            profile = PersonProfile(person_id=person.id)
            session.add(profile)
        profile.bio = str(payload.get("bio") or "").strip()[:2000]
        profile.avatar_url = _profile_url(payload.get("avatarUrl"))
        profile.website_url = _profile_url(payload.get("websiteUrl"))
        profile.location = str(payload.get("location") or "").strip()[:255]
        links = payload.get("links") if isinstance(payload.get("links"), list) else []
        profile.links = [url for value in links[:10] if (url := _profile_url(value))]
        profile.visibility = "private" if payload.get("visibility") == "private" else "public"
        profile.updated_at = utcnow()
        session.flush()
        return jsonify({"profile": common.profile_payload(profile, person)})
