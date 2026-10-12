# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed-in account reads backed by the canonical people relationship graph."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import select

from backend import (
    authz,
    canonical_tools,
    catalog_projection,
    db,
    people_index,
    tool_summaries,
    toolinfo_discovery,
    toolinfo_sources,
    userscript_toolinfo,
    wiki_user_script_edits,
    wikimedia_urls,
)
from backend import v1_common as common
from backend.models import (
    CanonicalToolCache,
    CatalogCuration,
    CatalogToolProjection,
    PersonAccountBinding,
    PersonProfile,
    ToolAuthorClaim,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolPersonRelationship,
    User,
    UserScriptDirectoryEntry,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    SOURCE_WIKI_USERSCRIPT,
)

v1_me_bp = Blueprint("v1_me", __name__)

MAX_ME_WIKI_USER_SCRIPTS = 200


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
            return {
                "username": user.username,
                "identities": {"wikiUsername": user.username, "toolforgeDeveloperUsernames": []},
                "toolforgeProjects": [],
                "verified": [],
                "possible": [],
                "errors": [],
            }
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
        bindings = list(
            session.execute(
                select(PersonAccountBinding)
                .where(
                    PersonAccountBinding.person_id == person.id,
                    PersonAccountBinding.provider == "toolforge",
                    PersonAccountBinding.status == "verified",
                    PersonAccountBinding.revoked_at.is_(None),
                )
                .order_by(PersonAccountBinding.external_id)
            ).scalars()
        )
        developer_accounts = {
            binding.external_id: account.uid
            for binding in bindings
            if (account := session.get(ToolforgeAccountProjection, binding.external_id)) is not None
            and not account.disabled
        }
        project_developers: dict[str, set[str]] = {}
        if developer_accounts:
            memberships = session.execute(
                select(ToolforgeMembershipProjection.uid_number, ToolforgeMembershipProjection.tool_name)
                .where(ToolforgeMembershipProjection.uid_number.in_(developer_accounts))
                .order_by(ToolforgeMembershipProjection.tool_name, ToolforgeMembershipProjection.uid_number)
            ).all()
            for uid_number, project_name in memberships:
                project_developers.setdefault(project_name, set()).add(developer_accounts[uid_number])
        toolforge_projects = [
            {"name": project_name, "developerUsernames": sorted(usernames, key=str.casefold)}
            for project_name, usernames in sorted(project_developers.items(), key=lambda item: item[0].casefold())
        ]
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
                "toolforgeProjects": [
                    project
                    for project in canonical_tools.toolforge_project_names(name, record)
                    if project in project_developers
                ],
                "toolinfoDiscovery": discoveries.get(name, {"status": "pending"}),
                "toolinfoSource": sources.get(name),
            }
            bucket = verified if any(edge.verification_status == "verified" for edge in edges) else possible
            bucket.append(item)
        toolforge_names = [project["name"] for project in toolforge_projects]
        developer_usernames = sorted(set(developer_accounts.values()), key=str.casefold)
        return {
            "username": stored_user.username,
            "personId": person.public_id,
            "person": {"id": person.public_id, "displayName": person.display_name},
            "identities": {
                "wikiUsername": stored_user.username,
                "toolforgeDeveloperUsernames": developer_usernames,
            },
            "searchTerms": ["canonical-relationship-graph"],
            "toolforgeToolNames": toolforge_names,
            "toolforgeProjects": toolforge_projects,
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


def _mediawiki_username_spellings(value: str) -> set[str]:
    """Keep MediaWiki's first-letter casing rule without folding real account names together."""
    username = wikimedia_urls.canonical_username(value)
    if not username:
        return set()
    return {
        spelling.replace(" ", separator)
        for first in (username[0].lower(), username[0].upper())
        for spelling in (first + username[1:],)
        for separator in (" ", "_")
    }


@v1_me_bp.route("/v1/me/wiki-user-scripts/")
@login_required
def v1_me_wiki_user_scripts() -> Response:
    """List public script candidates and this account's own edit-history tools."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees a session
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    usernames = _mediawiki_username_spellings(user.username)

    with db.session_scope() as session:
        directory_rows = list(
            session.execute(
                select(UserScriptDirectoryEntry)
                .where(UserScriptDirectoryEntry.owner.in_(usernames or {""}))
                .order_by(UserScriptDirectoryEntry.wiki, UserScriptDirectoryEntry.title)
                .limit(MAX_ME_WIKI_USER_SCRIPTS + 1)
            ).scalars()
        )
        directory_truncated = len(directory_rows) > MAX_ME_WIKI_USER_SCRIPTS
        directory_rows = directory_rows[:MAX_ME_WIKI_USER_SCRIPTS]
        candidate_entries = {
            name: entry
            for entry in directory_rows
            if (name := userscript_toolinfo.tool_name(entry.wiki, entry.owner, entry.basename))
        }
        history_names = list(
            session.execute(
                select(CatalogCuration.tool_name)
                .where(
                    CatalogCuration.created_by_user_id == user.id,
                    CatalogCuration.edit_kind == wiki_user_script_edits.OWNER_EDIT_KIND,
                )
                .distinct()
                .order_by(CatalogCuration.tool_name)
                .limit(MAX_ME_WIKI_USER_SCRIPTS + 1)
            ).scalars()
        )
        history_truncated = len(history_names) > MAX_ME_WIKI_USER_SCRIPTS
        history_names = history_names[:MAX_ME_WIKI_USER_SCRIPTS]
        names = sorted(set(candidate_entries) | set(history_names))
        truncated = directory_truncated or history_truncated or len(names) > MAX_ME_WIKI_USER_SCRIPTS
        names = names[:MAX_ME_WIKI_USER_SCRIPTS]
        canonical_by_name = {
            row.tool_name: row
            for row in session.execute(
                select(CanonicalToolCache).where(
                    CanonicalToolCache.tool_name.in_(names or {""}),
                    CanonicalToolCache.source == SOURCE_WIKI_USERSCRIPT,
                )
            ).scalars()
        }
        projection_by_name = {
            row.tool_name: row
            for row in session.execute(
                select(CatalogToolProjection).where(CatalogToolProjection.tool_name.in_(names or {""}))
            ).scalars()
        }
        entries: list[dict[str, Any]] = []
        for name in names:
            canonical = canonical_by_name.get(name)
            if canonical is None or not isinstance(canonical.record, dict):
                continue
            page = wikimedia_urls.user_space_javascript_page(canonical.source_url)
            if page is None:
                continue
            directory_entry = candidate_entries.get(name)
            if directory_entry is not None and wikimedia_urls.canonical_username(
                page.username
            ) != wikimedia_urls.canonical_username(directory_entry.owner):
                continue
            projection_row = projection_by_name.get(name)
            projection_record = (
                projection_row.effective_record
                if projection_row is not None
                and projection_row.projection_version == catalog_projection.PROJECTION_VERSION
                and isinstance(projection_row.effective_record, dict)
                else None
            )
            projection_available = projection_record is not None
            current_record = projection_record if projection_record is not None else canonical.record
            provenance = (
                projection_row.provenance
                if projection_record is not None
                and projection_row is not None
                and isinstance(projection_row.provenance, dict)
                else {}
            )
            owner_curated_fields = sorted(
                field
                for field, evidence in provenance.items()
                if isinstance(evidence, list)
                and any(
                    isinstance(item, dict)
                    and item.get("source") == catalog_projection.SOURCE_OWNER_CURATION
                    and item.get("effective")
                    for item in evidence
                )
            )
            entries.append(
                {
                    "toolName": name,
                    "title": str(
                        current_record.get("title") or (directory_entry.basename if directory_entry else name)
                    ),
                    "wiki": page.domain,
                    "owner": page.username,
                    "sourceUrl": canonical.source_url,
                    "sourceMetadata": {
                        field: canonical.record[field]
                        for field in sorted(wiki_user_script_edits.OWNER_EDIT_FIELDS)
                        if field in canonical.record
                    },
                    "currentMetadata": {
                        field: current_record[field]
                        for field in sorted(wiki_user_script_edits.OWNER_EDIT_FIELDS)
                        if field in current_record
                    },
                    "projectionAvailable": projection_available,
                    "ownerCuratedFields": owner_curated_fields,
                    "historyOnly": directory_entry is None,
                    "verificationRequired": True,
                }
            )

    response = jsonify({"entries": entries, "truncated": truncated})
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
