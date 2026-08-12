# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticated external-account reconnection endpoints."""

from flask import Blueprint, Response, jsonify, request

from backend import account_linking, db, identity_graph
from backend.models import User
from backend.security import current_user_id, login_required, write_guard

v1_account_links_bp = Blueprint("v1_account_links", __name__)


def _user_or_response():  # noqa: ANN202 - returns a model/Response union
    user_id = current_user_id()
    if user_id is None:
        response = jsonify({"error": "sign in required"})
        response.status_code = 401
        return None, response
    return user_id, None


def _bad_link(error: account_linking.AccountLinkError) -> Response:
    response = jsonify({"error": str(error)})
    response.status_code = 409
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v1_account_links_bp.route("/v1/me/account-links/")
@login_required
def account_links_get() -> Response:
    """List verified links, safe candidates, and available proof methods."""
    user_id, error = _user_or_response()
    if error is not None:
        return error
    with db.session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return _bad_link(account_linking.AccountLinkError("sign in required"))
        response = jsonify(account_linking.link_state(session, user))
        response.headers["Cache-Control"] = "private, no-store"
        return response


@v1_account_links_bp.route("/v1/me/account-links/toolforge/challenges/", methods=["POST"])
@write_guard
def account_link_challenge_create() -> Response:
    """Start an SSH-signature proof for one Toolforge developer account."""
    user_id, error = _user_or_response()
    if error is not None:
        return error
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _bad_link(account_linking.AccountLinkError("JSON object required"))
    try:
        with db.session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                return _bad_link(account_linking.AccountLinkError("sign in required"))
            try:
                result = account_linking.start_toolforge_challenge(session, user, str(payload.get("username") or ""))
            except account_linking.AccountLinkError as exc:
                return _bad_link(exc)
            response = jsonify(result)
            response.status_code = 201
            response.headers["Cache-Control"] = "private, no-store"
            return response
    except account_linking.AccountLinkError as exc:
        return _bad_link(exc)


@v1_account_links_bp.route("/v1/me/account-links/toolforge/verify/", methods=["POST"])
@write_guard
def account_link_challenge_verify() -> Response:
    """Consume a Toolforge SSH-signature proof and create a durable binding."""
    user_id, error = _user_or_response()
    if error is not None:
        return error
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _bad_link(account_linking.AccountLinkError("JSON object required"))
    try:
        with db.session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                return _bad_link(account_linking.AccountLinkError("sign in required"))
            try:
                result = account_linking.complete_toolforge_challenge(
                    session,
                    user,
                    challenge_id=str(payload.get("challengeId") or ""),
                    challenge=str(payload.get("challenge") or ""),
                    signature=str(payload.get("signature") or ""),
                )
            except (account_linking.AccountLinkError, identity_graph.IdentityBindingConflictError) as exc:
                return _bad_link(account_linking.AccountLinkError(str(exc)))
            response = jsonify(result)
            response.headers["Cache-Control"] = "private, no-store"
            return response
    except (account_linking.AccountLinkError, identity_graph.IdentityBindingConflictError) as exc:
        return _bad_link(account_linking.AccountLinkError(str(exc)))
