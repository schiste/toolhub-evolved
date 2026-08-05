# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/author-keys/* endpoints, split out of backend/v1.py.

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
)
from backend import v1_common as common
from backend.author_claims import (
    validate_ed25519_public_key,
)
from backend.models import (
    ToolAuthorKey,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard

v1_author_keys_bp = Blueprint("v1_author_keys", __name__)


@v1_author_keys_bp.route("/v1/author-keys/")
@login_required
def v1_author_keys() -> Response:
    """List public keys registered by the signed-in Toolhub user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        keys = [
            common.author_key_payload(row)
            for row in s.execute(
                select(ToolAuthorKey)
                .where(common.author_key_owned_by(user))
                .order_by(ToolAuthorKey.revoked_at.is_not(None), ToolAuthorKey.created_at, ToolAuthorKey.id)
            ).scalars()
        ]
    return jsonify({"username": user.username, "keys": keys})


@v1_author_keys_bp.route("/v1/author-keys/", methods=["POST"])
@write_guard
def v1_author_key_create() -> Response:
    """Register one public key for signed-toolinfo verification."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = common.json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — common.json_object_body returned no error
    key_id = common.clean_author_key_id(common.payload_value(body, "keyId", "key_id"))
    if key_id is None:
        return common.bad("keyId must use 1-128 letters, digits, dots, colons, underscores or hyphens")
    algorithm = str(common.payload_value(body, "algorithm") or "ed25519").strip().lower()
    if algorithm != "ed25519":
        return common.bad("only ed25519 public keys are supported")
    try:
        public_key = validate_ed25519_public_key(str(common.payload_value(body, "publicKey", "public_key") or ""))
    except (TypeError, ValueError) as exc:
        return common.bad(str(exc))
    with db.session_scope() as s:
        existing = s.execute(
            select(ToolAuthorKey).where(common.author_key_owned_by(user), ToolAuthorKey.key_id == key_id)
        ).scalar_one_or_none()
        if existing is not None:
            return common.deny(common.HTTP_CONFLICT, "key id already exists")
        row = ToolAuthorKey(
            toolhub_username=user.username,
            user_id=user.id,
            key_id=key_id,
            public_key=public_key,
            algorithm=algorithm,
        )
        s.add(row)
        s.flush()
        payload = common.author_key_payload(row)
    resp = jsonify({"ok": True, "key": payload})
    resp.status_code = 201
    return resp


@v1_author_keys_bp.route("/v1/author-keys/<key_id>/", methods=["DELETE"])
@write_guard
def v1_author_key_revoke(key_id: str) -> Response:
    """Revoke one registered public key for the signed-in Toolhub user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    clean_key_id = common.clean_author_key_id(key_id)
    if clean_key_id is None:
        return common.bad("invalid key id")
    with db.session_scope() as s:
        row = s.execute(
            select(ToolAuthorKey).where(
                common.author_key_owned_by(user),
                ToolAuthorKey.key_id == clean_key_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return common.deny(common.HTTP_NOT_FOUND, "public key not found")
        if row.revoked_at is None:
            row.revoked_at = utcnow()
        payload = common.author_key_payload(row)
    return jsonify({"ok": True, "key": payload})
