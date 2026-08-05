# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/toolinfo/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

import base64
import json
from typing import Any

from flask import Blueprint, Response, jsonify
from sqlalchemy import select

from backend import (
    authz,
    db,
    v1,
)
from backend.author_claims import (
    SIGNATURE_META_KEY,
    canonical_toolinfo_string,
)
from backend.models import (
    ToolAuthorKey,
    ToolinfoControlChallenge,
)
from backend.security import current_user_id, login_required, write_guard
from backend.toolinfo_control import (
    CHALLENGE_FIELD,
    CHALLENGE_STATUS_EXPIRED,
    CHALLENGE_STATUS_PENDING,
    challenge_payload,
)
from backend.toolinfo_control import (
    expired as challenge_expired,
)

v1_toolinfo_bp = Blueprint("v1_toolinfo", __name__)


def _toolinfo_body(value: Any) -> dict | None:  # noqa: ANN401 - untrusted JSON
    """Return one toolinfo object from JSON input."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    return value if v1._clean_name(value.get("name")) is not None else None


def _signature_metadata(key_id: str) -> dict:
    """Return the metadata block a maintainer adds after signing."""
    return {"algorithm": "ed25519", "key_id": key_id, "signature": v1.SIGNATURE_PLACEHOLDER}


@v1_toolinfo_bp.route("/v1/toolinfo/ownership-challenges/")
@login_required
def v1_toolinfo_control_challenges() -> Response:
    """List URL-control challenges belonging to the signed-in account."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolinfoControlChallenge)
                .where(ToolinfoControlChallenge.user_id == user.id)
                .order_by(ToolinfoControlChallenge.created_at.desc(), ToolinfoControlChallenge.id.desc())
                .limit(50)
            ).scalars()
        )
        for row in rows:
            if row.status == CHALLENGE_STATUS_PENDING and challenge_expired(row):
                row.status = CHALLENGE_STATUS_EXPIRED
        payload = [challenge_payload(row) for row in rows]
    return jsonify({"challenges": payload, "field": CHALLENGE_FIELD})


@v1_toolinfo_bp.route("/v1/toolinfo/ownership-challenges/", methods=["POST"])
@write_guard
def v1_toolinfo_control_challenge_create() -> Response:
    """Create a proof-of-control challenge after validating the exact URL."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - write_guard guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = v1._json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 - v1._json_object_body returned no error
    tool_name = v1._clean_name(str(v1._payload_value(body, "toolName", "tool_name") or "").strip())
    if tool_name is None:
        return v1._bad("toolName is required")
    toolinfo_url = str(v1._payload_value(body, "toolinfoUrl", "toolinfo_url") or "").strip()
    with db.session_scope() as s:
        row, error = v1._create_control_challenge(s, user, tool_name, toolinfo_url)
        if error is not None:
            return error
        assert row is not None  # noqa: S101 - helper returned no error
        payload = challenge_payload(row)
    response = jsonify({"ok": True, "challenge": payload, "field": CHALLENGE_FIELD})
    response.status_code = 201
    return response


@v1_toolinfo_bp.route("/v1/toolinfo/ownership-challenges/<int:challenge_id>/verify/", methods=["POST"])
@write_guard
def v1_toolinfo_control_challenge_verify(challenge_id: int) -> Response:
    """Refetch the URL and materialize a verified per-tool maintainer claim."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - write_guard guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        row = s.execute(
            select(ToolinfoControlChallenge).where(
                ToolinfoControlChallenge.id == challenge_id,
                ToolinfoControlChallenge.user_id == user.id,
            )
        ).scalar_one_or_none()
        if row is None:
            return v1._deny(v1.HTTP_NOT_FOUND, "ownership challenge not found")
        claim, error = v1._verify_control_challenge_record(s, user, row)
        if error is not None:
            return error
        assert claim is not None  # noqa: S101 - helper returned no error
        payload = challenge_payload(row)
        claim_data = v1._claim_payload(claim)
    return jsonify({"ok": True, "challenge": payload, "claim": claim_data})


@v1_toolinfo_bp.route("/v1/toolinfo/signing-payload/", methods=["POST"])
@write_guard
def v1_toolinfo_signing_payload() -> Response:
    """Return the canonical toolinfo bytes that a registered key should sign."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    body, bad = v1._json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — v1._json_object_body returned no error
    key_id = v1._clean_author_key_id(v1._payload_value(body, "keyId", "key_id"))
    if key_id is None:
        return v1._bad("choose a registered key id")
    toolinfo = _toolinfo_body(v1._payload_value(body, "toolinfo"))
    if toolinfo is None:
        return v1._bad("toolinfo must be one JSON object with a valid name")
    with db.session_scope() as s:
        key = s.execute(
            select(ToolAuthorKey).where(
                v1._author_key_owned_by(user),
                ToolAuthorKey.key_id == key_id,
                ToolAuthorKey.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        if key is None:
            return v1._deny(v1.HTTP_NOT_FOUND, "active public key not found")
    canonical_payload = canonical_toolinfo_string(toolinfo)
    signature_metadata = _signature_metadata(key_id)
    return jsonify(
        {
            "toolName": v1._clean_name(toolinfo.get("name")),
            "keyId": key_id,
            "algorithm": "ed25519",
            "signatureField": SIGNATURE_META_KEY,
            "canonicalPayload": canonical_payload,
            "canonicalPayloadBase64": base64.b64encode(canonical_payload.encode("utf-8")).decode("ascii"),
            "signatureMetadata": signature_metadata,
            "signedToolinfoPreview": {**toolinfo, SIGNATURE_META_KEY: signature_metadata},
        }
    )
