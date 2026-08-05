# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/claims/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from flask import Blueprint, Response, jsonify
from sqlalchemy import select

from backend import (
    authz,
    db,
    maintainer_index,
    v1,
)
from backend.models import (
    ToolAuthorClaim,
    ToolinfoControlChallenge,
    User,
    utcnow,
)
from backend.security import current_user_id, write_guard
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    clean_error,
    clean_int,
)
from backend.toolinfo_control import (
    CHALLENGE_STATUS_EXPIRED,
    CHALLENGE_STATUS_PENDING,
    challenge_payload,
    fetch_matching_item,
)

v1_claims_bp = Blueprint("v1_claims", __name__)


@v1_claims_bp.route("/v1/claims/<int:claim_id>/verify/", methods=["POST"])
@write_guard
def v1_claim_verify(claim_id: int) -> Response:  # noqa: C901, PLR0911
    """Re-run the proof provider for one active account-owned claim."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - write_guard guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        stored_user = s.get(User, user.id)
        row = s.execute(
            select(ToolAuthorClaim).where(ToolAuthorClaim.id == claim_id, v1._author_claim_owned_by(user))
        ).scalar_one_or_none()
        if stored_user is None or row is None:
            return v1._deny(v1.HTTP_NOT_FOUND, "claim not found")
        if row.revoked_at is not None:
            return v1._deny(v1.HTTP_CONFLICT, "revoked claims cannot be verified")
        method = row.verification_method
        if method == AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME:
            return v1._deny(v1.HTTP_CONFLICT, "a listed author name is identity evidence and cannot self-verify")
        if method == AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS:
            return v1._deny(v1.HTTP_CONFLICT, "Toolhub record authority is verified automatically")
        if method == AUTHOR_CLAIM_TOOLINFO_URL_CONTROL:
            evidence = row.evidence_payload if isinstance(row.evidence_payload, dict) else {}
            challenge_id = clean_int(evidence.get("challengeId"))
            challenge = s.get(ToolinfoControlChallenge, challenge_id) if challenge_id is not None else None
            if challenge is None or challenge.user_id != stored_user.id:
                return v1._deny(v1.HTTP_NOT_FOUND, "claim challenge not found")
            updated, error = v1._verify_control_challenge_record(s, stored_user, challenge)
            if error is not None:
                return error
            assert updated is not None  # noqa: S101 - helper returned no error
            return jsonify({"ok": True, "claim": v1._claim_payload(updated), "challenge": challenge_payload(challenge)})
        tool, error = v1._claim_tool_or_error(row.tool_name)
        if error is not None:
            return error
        assert tool is not None  # noqa: S101 - helper returned no error
        if method == AUTHOR_CLAIM_TOOLFORGE_MAINTAINER:
            rows = v1.TOOLFORGE_MAINTAINER_PROVIDER.verify(
                s,
                stored_user,
                tool_name=row.tool_name,
                author_names=[row.author_name],
                toolhub_tool=tool,
            )
            updated = rows[0] if rows else row
        elif method == AUTHOR_CLAIM_SIGNED_TOOLINFO:
            try:
                item = fetch_matching_item(row.evidence_url or "", row.tool_name)
            except Exception as exc:  # noqa: BLE001 - normalize bounded external proof failures
                return v1._bad(f"Could not read signed toolinfo: {clean_error(str(exc)) or 'fetch failed'}")
            rows = v1.SIGNED_TOOLINFO_PROVIDER.verify(s, stored_user, toolinfo=item, evidence_url=row.evidence_url)
            updated = rows[0] if rows else row
        else:
            return v1._bad("unsupported claim method")
        s.flush()
        maintainer_index.sync_author_claim_edges(s, tool_names=[row.tool_name], user_ids=[stored_user.id])
        return jsonify({"ok": True, "claim": v1._claim_payload(updated)})


@v1_claims_bp.route("/v1/claims/<int:claim_id>/", methods=["DELETE"])
@write_guard
def v1_claim_revoke(claim_id: int) -> Response:
    """Revoke one local claim and withdraw its derived relationship evidence."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - write_guard guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        row = s.execute(
            select(ToolAuthorClaim).where(ToolAuthorClaim.id == claim_id, v1._author_claim_owned_by(user))
        ).scalar_one_or_none()
        if row is None:
            return v1._deny(v1.HTTP_NOT_FOUND, "claim not found")
        row.revoked_at = row.revoked_at or utcnow()
        row.updated_at = utcnow()
        evidence = row.evidence_payload if isinstance(row.evidence_payload, dict) else {}
        challenge_id = clean_int(evidence.get("challengeId"))
        challenge = s.get(ToolinfoControlChallenge, challenge_id) if challenge_id is not None else None
        if challenge is not None and challenge.user_id == user.id and challenge.status == CHALLENGE_STATUS_PENDING:
            challenge.status = CHALLENGE_STATUS_EXPIRED
        maintainer_index.sync_author_claim_edges(s, tool_names=[row.tool_name], user_ids=[user.id])
        return jsonify({"ok": True, "claim": v1._claim_payload(row)})
