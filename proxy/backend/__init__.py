# SPDX-License-Identifier: GPL-3.0-or-later
"""Server-side backend for Toolhub Evolved (the "project-specific database").

The live Toolhub API stays the only source for upstream catalog data (served by
the read-only proxy in app.py). This package adds what the API cannot give us —
Toolhub OAuth sign-in, stored official grants, the official write bridge, and
the site's own complementary overlay records. See docs/PRODUCTION.md for the
architecture.
"""

import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask

from backend import db, token_crypto
from backend.oauth import oauth_bp
from backend.v1 import v1_bp
from backend.v1_accounts import v1_accounts_bp
from backend.v1_author_keys import v1_author_keys_bp
from backend.v1_catalog import v1_catalog_bp
from backend.v1_claims import v1_claims_bp
from backend.v1_crawler import v1_crawler_bp
from backend.v1_me import v1_me_bp
from backend.v1_moderation import v1_moderation_bp
from backend.v1_overlay import v1_overlay_bp
from backend.v1_people import v1_people_bp
from backend.v1_source_analysis import v1_source_analysis_bp
from backend.v1_toolhub import v1_toolhub_bp
from backend.v1_toolinfo import v1_toolinfo_bp
from backend.v1_tools import v1_tools_bp
from backend.v1_user import v1_user_bp
from backend.v1_write import v1_write_bp

DEFAULT_DB_URL = f"sqlite:///{Path(__file__).resolve().parent.parent / 'var' / 'app.sqlite3'}"
SESSION_DAYS = 30
DEV_ENV = "TOOLHUB_INSECURE_COOKIES"


def _session_secret(secret_key: str | None) -> str:
    """Resolve the session signing key, failing closed when it is unset.

    A per-process random key is not a safe default in production: every worker
    signs sessions with a different value, so sign-in appears to work and then
    randomly forgets users, with nothing in the logs to say why. Refusing to
    start makes the misconfiguration loud. Local development already announces
    itself with TOOLHUB_INSECURE_COOKIES=1, so that is the one place an
    ephemeral key is still allowed.
    """
    explicit = secret_key or os.environ.get("TOOLHUB_SECRET_KEY")
    if explicit:
        return explicit
    if os.environ.get(DEV_ENV) == "1":
        return secrets.token_hex(32)
    msg = (
        "TOOLHUB_SECRET_KEY is required: without a stable value each worker signs "
        f"sessions with a different key. Set it, or set {DEV_ENV}=1 for local development."
    )
    raise RuntimeError(msg)


def register(app: Flask, *, db_url: str | None = None, secret_key: str | None = None) -> None:
    """Wire the backend into a Flask app: config, database schema, blueprints.

    Explicit arguments win over the environment; the environment wins over the
    dev default (a repo-local SQLite file). There is no default session secret:
    see _session_secret. On Toolforge, TOOLHUB_DB_URL points at ToolsDB and
    TOOLHUB_SECRET_KEY is a stable random value in the tool account's env file
    (see docs/RUNBOOK.md).
    """
    url = db_url or os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL
    parent = Path(url.removeprefix("sqlite:///")).parent if url.startswith("sqlite:///") else None
    if parent:  # file-backed SQLite: make sure its directory exists
        parent.mkdir(parents=True, exist_ok=True)
    app.secret_key = _session_secret(secret_key)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get(DEV_ENV) != "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    token_crypto.configure(app.secret_key)
    db.configure(url)
    db.init_schema()
    app.register_blueprint(oauth_bp)
    app.register_blueprint(v1_bp)
    app.register_blueprint(v1_write_bp)
    app.register_blueprint(v1_crawler_bp)
    app.register_blueprint(v1_claims_bp)
    app.register_blueprint(v1_accounts_bp)
    app.register_blueprint(v1_people_bp)
    app.register_blueprint(v1_user_bp)
    app.register_blueprint(v1_catalog_bp)
    app.register_blueprint(v1_tools_bp)
    app.register_blueprint(v1_toolinfo_bp)
    app.register_blueprint(v1_source_analysis_bp)
    app.register_blueprint(v1_moderation_bp)
    app.register_blueprint(v1_author_keys_bp)
    app.register_blueprint(v1_toolhub_bp)
    app.register_blueprint(v1_overlay_bp)
    app.register_blueprint(v1_me_bp)
