# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/tools/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from datetime import timedelta
from typing import Any
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select

from backend import (
    authz,
    db,
    maintainer_index,
    people_index,
    people_policy,
    tool_summaries,
    toolhub,
    v1,
)
from backend import v1_common as common
from backend.author_claims import (
    DISPLAY_NAME_CLAIM_TTL,
    author_names_from_toolhub_tool,
    record_author_claim,
    toolforge_names_from_toolhub_tool,
)
from backend.models import (
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolEvent,
    ToolHealthTarget,
    ToolhubToken,
    ToolMedia,
    ToolPersonRelationship,
    ToolThanks,
    User,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_UNVERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
    PERSON_REL_RECORD_OWNER,
    REVIEW_APPROVED,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SOURCE_OFFICIAL,
    SYNC_EVOLVED_REAL,
    clean_error,
    clean_review_status,
)
from backend.toolinfo_control import (
    CHALLENGE_FIELD,
    challenge_payload,
    fetch_matching_item,
)

v1_tools_bp = Blueprint("v1_tools", __name__)


def _is_http_url(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, str) and value.startswith(("http://", "https://")) and len(value) <= common.MAX_URL


@v1_tools_bp.route("/v1/tools/<name>/viewer-context/")
@login_required
def v1_tool_viewer_context(name: str) -> Response:
    """Return private relationship-derived wording context for one viewer and tool."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    tool_name = str(name or "").strip()[:255]
    now = utcnow()
    with db.session_scope() as s:
        stored_user = s.get(User, user.id)
        if stored_user is None:
            return common.deny(common.HTTP_UNAUTHORIZED, "sign in required")
        person = people_index.link_user(s, stored_user)
        rows = list(
            s.execute(
                select(ToolPersonRelationship)
                .where(
                    ToolPersonRelationship.tool_name == tool_name,
                    ToolPersonRelationship.person_id == person.id,
                )
                .order_by(ToolPersonRelationship.relationship_type)
            ).scalars()
        )
        relationships = [
            {
                "type": row.relationship_type,
                "status": row.verification_status,
                "confidence": row.confidence,
                "evidenceCount": row.evidence_count,
                "expiresAt": common.iso(row.expires_at),
            }
            for row in rows
            if row.verification_status == "verified" and (row.expires_at is None or row.expires_at > now)
        ]
        audience = people_policy.viewer_action_audience(
            [
                {
                    "type": row.relationship_type,
                    "status": row.verification_status,
                    "expires_at": row.expires_at,
                }
                for row in rows
            ],
            checked_at=now,
        )
        response = jsonify(
            {
                "toolName": tool_name,
                "personId": person.public_id,
                "audience": audience,
                "qualifyingRelationships": relationships,
            }
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response


def _claim_options(s: Any, user: User, tool: dict) -> dict[str, Any]:  # noqa: ANN401 - SQLAlchemy session
    """Describe user-specific proof paths without treating any option as a grant."""
    tool_name = str(tool.get("name") or "")
    author_names = author_names_from_toolhub_tool(tool)
    toolforge_names = toolforge_names_from_toolhub_tool(tool_name, tool)
    active_key_count = int(
        s.execute(
            select(func.count())
            .select_from(ToolAuthorKey)
            .where(common.author_key_owned_by(user), ToolAuthorKey.revoked_at.is_(None))
        ).scalar_one()
    )
    claims = list(
        s.execute(
            select(ToolAuthorClaim)
            .where(ToolAuthorClaim.tool_name == tool_name, common.author_claim_owned_by(user))
            .order_by(ToolAuthorClaim.created_at.desc(), ToolAuthorClaim.id.desc())
        ).scalars()
    )
    return {
        "tool": {"name": tool_name, "title": tool.get("title") or tool_name, "source": SOURCE_OFFICIAL},
        "personId": people_index.link_user(s, user).public_id,
        "options": [
            {
                "method": AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                "relationship": PERSON_REL_MAINTAINER,
                "available": bool(toolforge_names),
                "toolforgeNames": toolforge_names,
                "requires": [],
            },
            {
                "method": AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
                "relationship": PERSON_REL_MAINTAINER,
                "available": True,
                "requires": ["toolinfoUrl"],
                "challengeField": CHALLENGE_FIELD,
            },
            {
                "method": AUTHOR_CLAIM_SIGNED_TOOLINFO,
                "relationship": PERSON_REL_MAINTAINER,
                "available": active_key_count > 0,
                "requires": ["toolinfoUrl"],
                "activeKeyCount": active_key_count,
            },
            {
                "method": AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                "relationship": PERSON_REL_AUTHOR,
                "available": bool(author_names),
                "requires": ["authorName"],
                "authorNames": author_names,
            },
            {
                "method": AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
                "relationship": PERSON_REL_RECORD_OWNER,
                "available": s.get(ToolhubToken, user.id) is not None,
                "automatic": True,
                "requires": [],
            },
        ],
        "claims": [common.claim_payload(row) for row in claims],
        "canonicalAuthority": {"catalog": "toolhub", "claims": "toolhub-evolved"},
    }


@v1_tools_bp.route("/v1/tools/<name>/claim-options/")
@login_required
def v1_tool_claim_options(name: str) -> Response:
    """Return proof methods and existing claims for one canonical Toolhub tool."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    tool, error = common.claim_tool_or_error(name)
    if error is not None:
        return error
    assert tool is not None  # noqa: S101 - helper returned no error
    with db.session_scope() as s:
        stored_user = s.get(User, user.id)
        if stored_user is None:
            return common.deny(common.HTTP_UNAUTHORIZED, "sign in required")
        return jsonify(_claim_options(s, stored_user, tool))


@v1_tools_bp.route("/v1/tools/<name>/claims/", methods=["POST"])
@write_guard
def v1_tool_claim_create(name: str) -> Response:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Start or refresh one account-owned relationship proof workflow."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - write_guard guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = common.json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 - body parser returned no error
    method = str(common.payload_value(body, "method") or "").strip()
    if method not in v1.CLAIM_METHODS:
        return common.bad("unknown claim verification method")
    if method == AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS:
        return common.deny(
            common.HTTP_CONFLICT, "Toolhub record authority is recorded automatically after an official write"
        )
    tool, error = common.claim_tool_or_error(name)
    if error is not None:
        return error
    assert tool is not None  # noqa: S101 - helper returned no error
    tool_name = str(tool["name"])
    challenge = None
    rows: list[ToolAuthorClaim] = []
    with db.session_scope() as s:
        stored_user = s.get(User, user.id)
        if stored_user is None:
            return common.deny(common.HTTP_UNAUTHORIZED, "sign in required")
        if method == AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME:
            canonical_names = author_names_from_toolhub_tool(tool)
            author_name = str(common.payload_value(body, "authorName", "author_name") or "").strip()
            selected = next((value for value in canonical_names if value.casefold() == author_name.casefold()), None)
            if selected is None:
                return common.bad("authorName must be one of the names on the canonical Toolhub record")
            rows = [
                record_author_claim(
                    s,
                    tool_name=tool_name,
                    author_name=selected,
                    toolhub_username=stored_user.username,
                    user_id=stored_user.id,
                    verification_status=AUTHOR_CLAIM_UNVERIFIED,
                    verification_method=method,
                    evidence_url=f"{toolhub.base_url()}/api/tools/{quote(tool_name, safe='')}/",
                    evidence_payload={"toolhubField": "author", "claimKind": "identity_association"},
                    expires_at=utcnow() + DISPLAY_NAME_CLAIM_TTL,
                )
            ]
        elif method == AUTHOR_CLAIM_TOOLFORGE_MAINTAINER:
            toolforge_names = toolforge_names_from_toolhub_tool(tool_name, tool)
            if not toolforge_names:
                return common.deny(common.HTTP_CONFLICT, "this Toolhub record does not identify a Toolforge tool")
            resolved = v1.PUBLIC_IDENTITY_RESOLVER.resolve(stored_user.wikimedia_global_user_id or "")
            toolforge_identity = resolved.toolforge if resolved is not None else None
            memberships = {
                value.casefold(): value for value in (toolforge_identity.tool_names if toolforge_identity else ())
            }
            matched = next((value for value in toolforge_names if value.casefold() in memberships), None)
            if not matched or toolforge_identity is None:
                return common.deny(
                    common.HTTP_CONFLICT,
                    "Toolforge membership could not be verified for this Wikimedia account",
                )
            rows = [
                v1.TOOLFORGE_MAINTAINER_PROVIDER.record_membership(
                    s,
                    stored_user,
                    tool_name=tool_name,
                    toolforge_name=matched,
                    toolforge_username=toolforge_identity.uid,
                )
            ]
        elif method == AUTHOR_CLAIM_TOOLINFO_URL_CONTROL:
            toolinfo_url = str(common.payload_value(body, "toolinfoUrl", "toolinfo_url") or "").strip()
            challenge, challenge_error = common.create_control_challenge(s, stored_user, tool_name, toolinfo_url)
            if challenge_error is not None:
                return challenge_error
            assert challenge is not None  # noqa: S101 - helper returned no error
            rows = [
                record_author_claim(
                    s,
                    tool_name=tool_name,
                    author_name=stored_user.username,
                    toolhub_username=stored_user.username,
                    user_id=stored_user.id,
                    verification_status=AUTHOR_CLAIM_UNVERIFIED,
                    verification_method=method,
                    evidence_url=toolinfo_url,
                    evidence_payload={"challengeId": challenge.id, "field": CHALLENGE_FIELD},
                    expires_at=challenge.expires_at,
                )
            ]
        elif method == AUTHOR_CLAIM_SIGNED_TOOLINFO:
            toolinfo_url = str(common.payload_value(body, "toolinfoUrl", "toolinfo_url") or "").strip()
            url_error = common.url_validation_message(toolinfo_url, label="toolinfo URL")
            if url_error is not None:
                return common.url_validation_bad("toolinfoUrl", url_error)
            try:
                item = fetch_matching_item(toolinfo_url, tool_name)
            except Exception as exc:  # noqa: BLE001 - normalize bounded external proof failures
                return common.bad(f"Could not read signed toolinfo: {clean_error(str(exc)) or 'fetch failed'}")
            rows = v1.SIGNED_TOOLINFO_PROVIDER.verify(s, stored_user, toolinfo=item, evidence_url=toolinfo_url)
            if not rows:
                return common.bad("the matching toolinfo item has no supported signature metadata")
        s.flush()
        maintainer_index.sync_author_claim_edges(s, tool_names=[tool_name], user_ids=[stored_user.id])
        payload = [common.claim_payload(row) for row in rows]
        challenge_data = challenge_payload(challenge) if challenge is not None else None
    response = jsonify({"ok": True, "claims": payload, "challenge": challenge_data})
    response.status_code = 201
    return response


@v1_tools_bp.route("/v1/tools/summaries/")
def v1_tool_summaries() -> Response:
    """Return local Evolved health and maintainer summaries for visible tools."""
    names = common.tool_names_from_request()
    if not names:
        return common.public_json_response(
            {"count": 0, "results": {}, "cacheMeta": {}, "source": SOURCE_LOCAL, "syncStatus": SYNC_EVOLVED_REAL}
        )
    # Cards ask for the projected view; the tool detail page omits it and gets
    # the whole record.
    view = request.args.get("view") or tool_summaries.VIEW_FULL
    if view not in tool_summaries.VIEWS:
        return common.deny(common.HTTP_BAD_REQUEST, "unknown summary view")
    read = tool_summaries.summaries_for(names, common.build_local_tool_summary, view=view)
    return common.public_json_response(
        {
            "count": len(read.results),
            "results": read.results,
            "cacheMeta": read.cache_meta,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "cachePolicy": {
                "canonical": False,
                "upstream": False,
                "summary": (
                    "Materialized local Evolved summaries only; stale rows are served immediately "
                    "and refreshed asynchronously."
                ),
            },
        }
    )


@v1_tools_bp.route("/v1/tools/<name>/signals/")
def v1_tool_signals(name: str) -> Response:
    """Real Evolved-owned signal summary for one tool."""
    clean_name = common.clean_name(name)
    if clean_name is None:
        return common.bad("tool name is required")
    since = (utcnow() - timedelta(days=30)).date().isoformat()
    uid = current_user_id()
    with db.session_scope() as s:
        thanks_count = s.execute(
            select(func.count())
            .select_from(ToolThanks)
            .where(
                ToolThanks.tool_name == clean_name,
                ToolThanks.active.is_(True),
                ToolThanks.review_status == REVIEW_APPROVED,
            )
        ).scalar_one()
        user_thanked = (
            bool(
                s.execute(
                    select(ToolThanks.id).where(
                        ToolThanks.tool_name == clean_name,
                        ToolThanks.user_id == uid,
                        ToolThanks.active.is_(True),
                        ToolThanks.review_status == REVIEW_APPROVED,
                    )
                ).first()
            )
            if uid is not None
            else False
        )
        events_30d = s.execute(
            select(func.count()).select_from(ToolEvent).where(ToolEvent.tool_name == clean_name, ToolEvent.day >= since)
        ).scalar_one()
        health = s.execute(
            select(ToolHealthTarget)
            .where(ToolHealthTarget.tool_name == clean_name, ToolHealthTarget.enabled.is_(True))
            .where(ToolHealthTarget.deleted_at.is_(None))
            .where(ToolHealthTarget.review_status == REVIEW_APPROVED)
            .order_by(ToolHealthTarget.last_checked_at.desc(), ToolHealthTarget.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    return jsonify(
        {
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "syncLabel": common.sync_label(SYNC_EVOLVED_REAL),
            "thanks": {
                "count": int(thanks_count),
                "userThanked": user_thanked,
                "syncStatus": SYNC_EVOLVED_REAL,
                "syncLabel": common.sync_label(SYNC_EVOLVED_REAL),
            },
            "usage30d": {
                "count": int(events_30d),
                "label": "30-day Evolved usage",
                "syncStatus": SYNC_EVOLVED_REAL,
                "syncLabel": common.sync_label(SYNC_EVOLVED_REAL),
            },
            "health": {
                "status": health.last_status if health and health.last_status else "unknown",
                "checkedAt": common.iso(health.last_checked_at) if health else "",
                "targetUrl": health.target_url if health else "",
                "lastError": health.last_error if health else "",
                "reviewStatus": clean_review_status(health.review_status, REVIEW_APPROVED) if health else "",
                "syncStatus": SYNC_EVOLVED_REAL,
                "syncLabel": common.sync_label(SYNC_EVOLVED_REAL),
            },
        }
    )


@v1_tools_bp.route("/v1/tools/<name>/events/", methods=["POST"])
@write_guard
def v1_tool_event(name: str) -> Response:
    """Record one privacy-limited Evolved interaction event."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    common.require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    clean_name = common.clean_name(name)
    value = request.get_json(silent=True) or {}
    event_type = value.get("eventType") if isinstance(value, dict) else None
    if clean_name is None or event_type not in v1.EVENT_TYPES:
        return common.bad("eventType must be one of view, launch, save, list_add")
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            ToolEvent(
                tool_name=clean_name,
                event_type=event_type,
                user_id=uid,
                created_by_user_id=uid,
                day=now.date().isoformat(),
                event_meta=value.get("meta") if isinstance(value.get("meta"), dict) else None,
                created_at=now,
            )
        )
    return jsonify({"ok": True})


@v1_tools_bp.route("/v1/tools/<name>/thanks/", methods=["POST", "DELETE"])
@write_guard
def v1_tool_thanks(name: str) -> Response:
    """Add or remove the caller's Evolved thanks for one tool."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    if request.method == "POST":
        common.require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    else:
        common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    clean_name = common.clean_name(name)
    if clean_name is None:
        return common.bad("tool name is required")
    with db.session_scope() as s:
        row = s.execute(
            select(ToolThanks).where(ToolThanks.tool_name == clean_name, ToolThanks.user_id == uid)
        ).scalar_one_or_none()
        if row is None:
            row = ToolThanks(
                tool_name=clean_name,
                user_id=uid,
                created_by_user_id=uid,
                active=request.method == "POST",
                review_status=REVIEW_APPROVED,
            )
            s.add(row)
        else:
            if row.created_by_user_id is None:
                row.created_by_user_id = uid
            row.review_status = clean_review_status(row.review_status, REVIEW_APPROVED)
            row.active = request.method == "POST"
            row.updated_at = utcnow()
    return jsonify(
        {
            "ok": True,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "syncLabel": common.sync_label(SYNC_EVOLVED_REAL),
        }
    )


@v1_tools_bp.route("/v1/tools/<name>/health-target/", methods=["PUT"])
@write_guard
def v1_tool_health_target(name: str) -> Response:
    """Store the caller's Evolved health target URL for a tool."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    common.require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    clean_name = common.clean_name(name)
    value = request.get_json(silent=True) or {}
    target_url = value.get("url") if isinstance(value, dict) else None
    if clean_name is None or not _is_http_url(target_url):
        return common.bad("health target needs an http(s) url")
    with db.session_scope() as s:
        row = s.execute(
            select(ToolHealthTarget).where(
                ToolHealthTarget.tool_name == clean_name,
                ToolHealthTarget.created_by_user_id == uid,
            )
        ).scalar_one_or_none()
        if row is None:
            row = ToolHealthTarget(
                tool_name=clean_name,
                created_by_user_id=uid,
                target_url=target_url[: common.MAX_URL],
                source=SOURCE_LOCAL,
                sync_status=SYNC_EVOLVED_REAL,
                review_status=REVIEW_PENDING,
            )
            s.add(row)
        else:
            if row.target_url != target_url[: common.MAX_URL]:
                row.review_status = REVIEW_PENDING
            row.target_url = target_url[: common.MAX_URL]
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
            row.enabled = True
            row.deleted_at = None
            row.last_error = None
        s.flush()
        payload = common.health_target_payload(row)
    return jsonify({"ok": True, "healthTarget": payload})


def _tool_media_get(clean_name: str) -> Response:
    """Return approved public media for a tool."""
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolMedia)
                .where(
                    ToolMedia.tool_name == clean_name,
                    ToolMedia.deleted_at.is_(None),
                    ToolMedia.review_status == REVIEW_APPROVED,
                )
                .order_by(ToolMedia.created_at.desc(), ToolMedia.id.desc())
                .limit(12)
            ).scalars()
        )
    return jsonify({"count": len(rows), "results": [common.media_payload(row) for row in rows]})


def _tool_media_post(clean_name: str) -> Response:
    """Submit URL-based media metadata for Evolved moderation."""
    guard = write_guard(lambda: None)()
    if guard is not None:
        return guard
    user = common.require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    uid = user.id
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return common.bad("media body must be a JSON object")
    media_url = value.get("url")
    license_id = str(value.get("license") or "").strip()
    source = str(value.get("source") or "").strip()
    if not (_is_http_url(media_url) and license_id and source):
        return common.bad("media needs url, license, and source")
    with db.session_scope() as s:
        row = ToolMedia(
            tool_name=clean_name,
            user_id=uid,
            created_by_user_id=uid,
            url=str(media_url)[: common.MAX_URL],
            title=str(value.get("title") or "")[: common.MAX_NAME],
            license=license_id[: common.MAX_NAME],
            source=source[: common.MAX_URL],
            review_status=REVIEW_PENDING,
            sync_status=SYNC_EVOLVED_REAL,
        )
        s.add(row)
        s.flush()
        payload = common.media_payload(row)
    return jsonify({"ok": True, "media": payload})


@v1_tools_bp.route("/v1/tools/<name>/media/", methods=["GET", "POST"])
def v1_tool_media(name: str) -> Response:
    """List approved media, or submit URL-based media metadata for moderation.

    No @write_guard here because GET is public: the POST half applies the guard
    itself inside _tool_media_post. An audit that reads decorators alone will
    score this route as an unauthenticated write, so check there before believing it.
    """
    clean_name = common.clean_name(name)
    if clean_name is None:
        return common.bad("tool name is required")
    if request.method == "GET":
        return _tool_media_get(clean_name)
    return _tool_media_post(clean_name)
