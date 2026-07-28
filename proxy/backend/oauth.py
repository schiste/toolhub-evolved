# SPDX-License-Identifier: GPL-3.0-or-later
"""Official Toolhub OAuth 2.0 sign-in.

The consumer is registered on toolhub.wikimedia.org with the callback
https://<tool>.toolforge.org/oauth/callback and read/write scopes. A successful
grant gives Evolved both identity (GET /api/user/) and the authorization needed
to perform official Toolhub writes on the user's behalf.
"""

import logging
import os
import secrets

import requests
from flask import Blueprint, Response, jsonify, redirect, request, session, url_for
from sqlalchemy import select

from backend import authz, db, security, toolhub
from backend.models import User

oauth_bp = Blueprint("oauth", __name__)

HTTP_UNAVAILABLE = 503
_log = logging.getLogger(__name__)


def _login_failed(reason: str, detail: object = None) -> Response:
    """Log why a sign-in attempt failed, then send the user to the generic error page.

    The user-facing outcome stays deliberately vague — a sign-in page should not
    explain which half of the handshake broke. But swallowing the reason entirely
    makes a broken OAuth app indistinguishable from a stale nonce, which is exactly
    the position this endpoint was in: every failure looked identical from outside.
    Toolhub's own error body (invalid_client, invalid_grant, redirect_uri_mismatch)
    is the thing that identifies the fault, so it goes to the log. Codes and tokens
    are never included.
    """
    _log.warning("oauth sign-in failed: %s%s", reason, f" — {detail}" if detail is not None else "")
    return redirect("/?login=error")


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


def _callback_preconditions(state: object, redirect_uri: str | None) -> Response | None:
    """Return the refusal for a callback that must not reach the token exchange."""
    if not configured():
        return _login_failed("Toolhub OAuth is not configured")
    if redirect_uri is None:
        return _login_failed("no trusted callback URL (set TOOLHUB_EVOLVED_BASE_URL)")
    if not state or not request.args.get("code"):
        return _login_failed("callback arrived without a stored state or a code")
    if not secrets.compare_digest(str(request.args.get("state", "")), str(state)):
        return _login_failed("state mismatch (stale tab, or the session was replaced mid-flow)")
    return None


@oauth_bp.route("/oauth/callback")
def oauth_callback() -> Response:
    """Exchange the code, fetch the Toolhub user, sign into Evolved."""
    state = session.pop("oauth_state", None)
    redirect_uri = session.pop("oauth_redirect_uri", None) or _callback_url()
    rejected = _callback_preconditions(state, redirect_uri)
    if rejected is not None:
        return rejected
    try:
        token_payload = toolhub.exchange_code(code=request.args["code"], redirect_uri=redirect_uri)
        profile = toolhub.current_user(str(token_payload["access_token"]))
        toolhub_user_id, username = str(profile["id"]), str(profile["username"])
    except toolhub.ToolhubAPIError as exc:
        return _login_failed(f"Toolhub rejected the exchange (HTTP {exc.status_code})", exc.payload)
    except requests.HTTPError as exc:
        # exchange_code raises this via raise_for_status; the body names the cause,
        # e.g. invalid_client (bad secret) or redirect_uri_mismatch (wrong registration).
        body = exc.response.text[:500] if exc.response is not None else None
        status = exc.response.status_code if exc.response is not None else "?"
        return _login_failed(f"token endpoint returned HTTP {status}", body)
    except (requests.RequestException, toolhub.ToolhubAuthError, KeyError, ValueError) as exc:
        return _login_failed(f"{type(exc).__name__} during the exchange", exc)
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


@oauth_bp.route("/oauth/logout", methods=["POST"])
def oauth_logout() -> Response:
    """Drop the server session and return to the (read-only) home page.

    POST-only: as a GET this was reachable from any third-party page through an
    <img> tag or a plain link, so anyone could sign the user out — and now that
    sign-out bumps the session epoch, that would also strand their other
    sessions. POST plus SameSite=Lax stops the browser attaching the cookie to a
    cross-site submission at all, and the CSRF token is checked so this endpoint
    is guarded like every other write.
    """
    if not security.csrf_ok(request.form.get("csrf", "")):
        return redirect("/?logout=error")
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
