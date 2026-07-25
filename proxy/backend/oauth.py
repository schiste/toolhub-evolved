# SPDX-License-Identifier: GPL-3.0-or-later
"""Wikimedia OAuth 2.0 sign-in (authorization-code flow, confidential client).

The consumer is registered on meta.wikimedia.org with the callback
https://<tool>.toolforge.org/oauth/callback ; its id/secret arrive via the
TOOLHUB_OAUTH_CLIENT_ID / TOOLHUB_OAUTH_CLIENT_SECRET env vars (Toolforge: the
tool account's env file — see docs/RUNBOOK.md). Unconfigured (local dev), the
login route answers 503 and the SPA simply keeps its logged-out demo mode.
"""

import os
import secrets

import requests
from flask import Blueprint, Response, jsonify, redirect, request, session
from sqlalchemy import select

from backend import db
from backend.models import User

oauth_bp = Blueprint("oauth", __name__)

META = "https://meta.wikimedia.org/w/rest.php/oauth2"
HTTP_UNAVAILABLE = 503
_TIMEOUT = 20


def _client() -> tuple[str, str] | None:
    cid = os.environ.get("TOOLHUB_OAUTH_CLIENT_ID", "")
    secret = os.environ.get("TOOLHUB_OAUTH_CLIENT_SECRET", "")
    return (cid, secret) if cid and secret else None


@oauth_bp.route("/oauth/login")
def oauth_login() -> Response:
    """Start the flow: remember a state nonce, send the browser to Wikimedia."""
    client = _client()
    if client is None:
        resp = jsonify({"error": "OAuth is not configured on this server"})
        resp.status_code = HTTP_UNAVAILABLE
        return resp
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    return redirect(f"{META}/authorize?response_type=code&client_id={client[0]}&state={state}")


@oauth_bp.route("/oauth/callback")
def oauth_callback() -> Response:
    """Exchange the code for a token, fetch the profile, sign the user in."""
    client = _client()
    state = session.pop("oauth_state", None)
    if client is None or not state or request.args.get("state") != state or not request.args.get("code"):
        return redirect("/?login=error")
    try:
        token_resp = requests.post(
            f"{META}/access_token",
            data={
                "grant_type": "authorization_code",
                "code": request.args["code"],
                "client_id": client[0],
                "client_secret": client[1],
            },
            timeout=_TIMEOUT,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        profile_resp = requests.get(
            f"{META}/resource/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()
        wm_sub, username = str(profile["sub"]), str(profile["username"])
    except (requests.RequestException, KeyError, ValueError):
        return redirect("/?login=error")
    with db.session_scope() as s:
        user = s.execute(select(User).where(User.wm_sub == wm_sub)).scalar_one_or_none()
        if user is None:
            user = User(wm_sub=wm_sub, username=username)
            s.add(user)
            s.flush()
        else:
            user.username = username
        uid = user.id
    session.clear()
    session.permanent = True
    session["uid"] = uid
    session["csrf"] = secrets.token_urlsafe(32)
    return redirect("/")


@oauth_bp.route("/oauth/logout", methods=["POST", "GET"])
def oauth_logout() -> Response:
    """Drop the server session and return to the (read-only) home page."""
    session.clear()
    return redirect("/")
