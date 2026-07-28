# SPDX-License-Identifier: GPL-3.0-or-later
"""Official Toolhub OAuth 2.0 sign-in.

The consumer is registered on toolhub.wikimedia.org with the callback
https://<tool>.toolforge.org/oauth/callback and read/write scopes. A successful
grant gives Evolved both identity (GET /api/user/) and the authorization needed
to perform official Toolhub writes on the user's behalf.
"""

import os
import secrets

import requests
from flask import Blueprint, Response, jsonify, redirect, request, session, url_for
from sqlalchemy import select

from backend import authz, db, toolhub
from backend.models import User

oauth_bp = Blueprint("oauth", __name__)

HTTP_UNAVAILABLE = 503


def configured() -> bool:
    """Report whether the official Toolhub OAuth client is configured."""
    return toolhub.configured()


def _callback_url() -> str | None:
    """Return the externally registered OAuth callback URL, or None if unknown.

    url_for(_external=True) builds this from the request's Host header, and the
    scheme from X-Forwarded-Proto — both attacker-controlled. Toolhub echoes the
    redirect_uri it is given, so a poisoned Host on /oauth/login is a way to aim
    the authorization code at another origin. In production the URL therefore
    comes only from TOOLHUB_EVOLVED_BASE_URL; header derivation stays available
    for local development, where there is no registered callback to protect.
    """
    base = os.environ.get("TOOLHUB_EVOLVED_BASE_URL", "").rstrip("/")
    if base:
        return f"{base}/oauth/callback"
    if os.environ.get("TOOLHUB_INSECURE_COOKIES") == "1":
        scheme = request.headers.get("X-Forwarded-Proto") or request.scheme
        return url_for("oauth.oauth_callback", _external=True, _scheme=scheme)
    return None


@oauth_bp.route("/oauth/login")
def oauth_login() -> Response:
    """Start the flow: remember a state nonce, send the browser to Toolhub."""
    callback = _callback_url()
    if not configured() or callback is None:
        resp = jsonify({"error": "Toolhub OAuth is not configured on this server"})
        resp.status_code = HTTP_UNAVAILABLE
        return resp
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    session["oauth_redirect_uri"] = callback
    return redirect(toolhub.authorize_url(state=state, redirect_uri=callback))


@oauth_bp.route("/oauth/callback")
def oauth_callback() -> Response:
    """Exchange the code, fetch the Toolhub user, sign into Evolved."""
    state = session.pop("oauth_state", None)
    redirect_uri = session.pop("oauth_redirect_uri", None) or _callback_url()
    if (
        not configured()
        or redirect_uri is None
        or not state
        or not secrets.compare_digest(str(request.args.get("state", "")), str(state))
        or not request.args.get("code")
    ):
        return redirect("/?login=error")
    try:
        token_payload = toolhub.exchange_code(code=request.args["code"], redirect_uri=redirect_uri)
        profile = toolhub.current_user(str(token_payload["access_token"]))
        toolhub_user_id, username = str(profile["id"]), str(profile["username"])
    except (requests.RequestException, toolhub.ToolhubAPIError, toolhub.ToolhubAuthError, KeyError, ValueError):
        return redirect("/?login=error")
    with db.session_scope() as s:
        user = s.execute(select(User).where(User.wm_sub == toolhub_user_id)).scalar_one_or_none()
        if user is None:
            user = User(wm_sub=toolhub_user_id, username=username, role=authz.role_for_login(toolhub_user_id, username))
            s.add(user)
            s.flush()
        else:
            user.username = username
            user.role = authz.role_for_login(toolhub_user_id, username, user.role)
        uid, epoch = user.id, user.session_epoch or 0
    toolhub.save_grant(uid, token_payload)
    session.clear()
    session.permanent = True
    session["uid"] = uid
    session["epoch"] = epoch
    session["csrf"] = secrets.token_urlsafe(32)
    return redirect("/")


@oauth_bp.route("/oauth/logout", methods=["POST", "GET"])
def oauth_logout() -> Response:
    """Drop the server session and return to the (read-only) home page."""
    uid = session.get("uid")
    if isinstance(uid, int):
        toolhub.revoke_local_grant(uid)
        # Strand every cookie already issued to this user, not just this browser's.
        with db.session_scope() as s:
            user = s.get(User, uid)
            if user is not None:
                user.session_epoch = (user.session_epoch or 0) + 1
    session.clear()
    return redirect("/")
