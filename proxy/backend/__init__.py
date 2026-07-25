# SPDX-License-Identifier: GPL-3.0-or-later
"""Server-side backend for Toolhub Evolved (the "project-specific database").

The live Toolhub API stays the only source for upstream catalog data (served by
the read-only proxy in app.py). This package adds what the API cannot give us —
real Wikimedia sign-in and the site's own complementary records: favorites,
lists, tool registrations, edit/annotation overlays, activity history, and
crawler URLs. See docs/PRODUCTION.md for the architecture.
"""

import os
import secrets
from datetime import timedelta

from flask import Flask

from backend import db
from backend.oauth import oauth_bp
from backend.v1 import v1_bp

DEFAULT_DB_URL = "sqlite:///" + os.path.join(os.path.dirname(os.path.dirname(__file__)), "var", "app.sqlite3")  # noqa: PTH118, PTH120
SESSION_DAYS = 30


def register(app: Flask, *, db_url: str | None = None, secret_key: str | None = None) -> None:
    """Wire the backend into a Flask app: config, database schema, blueprints.

    Explicit arguments win over the environment; the environment wins over dev
    defaults (a repo-local SQLite file and an ephemeral per-process secret).
    On Toolforge, TOOLHUB_DB_URL points at ToolsDB and TOOLHUB_SECRET_KEY is a
    stable random value in the tool account's env file (see docs/RUNBOOK.md).
    """
    url = db_url or os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL
    parent = os.path.dirname(url.removeprefix("sqlite:///")) if url.startswith("sqlite:///") else ""  # noqa: PTH120
    if parent:  # file-backed SQLite: make sure its directory exists
        os.makedirs(parent, exist_ok=True)  # noqa: PTH103
    app.secret_key = secret_key or os.environ.get("TOOLHUB_SECRET_KEY") or secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("TOOLHUB_INSECURE_COOKIES") != "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    db.configure(url)
    db.init_schema()
    app.register_blueprint(oauth_bp)
    app.register_blueprint(v1_bp)
