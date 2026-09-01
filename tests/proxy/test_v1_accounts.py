# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_accounts.py: /v1/accounts/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database, without
importing from tests/proxy/test_backend.py. Targets the branches that whole
module (rate limiting, oversized query params) leaves uncovered when only
the happy paths are exercised elsewhere.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1_accounts as v1_accounts_api  # noqa: E402
from backend import security  # noqa: E402


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_v1_accounts_rate_limited(client, monkeypatch):
    monkeypatch.setattr(v1_accounts_api.security, "read_rate_limited", lambda addr: True)
    resp = client.get("/v1/accounts/")
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "rate limit exceeded"


def test_v1_accounts_query_too_long(client):
    resp = client.get("/v1/accounts/", query_string={"q": "x" * 256})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "q must be 255 characters or fewer"


def test_v1_accounts_group_too_long(client):
    resp = client.get("/v1/accounts/", query_string={"group": "x" * 256})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "group must be 255 characters or fewer"


def test_v1_account_detail_rate_limited(client, monkeypatch):
    monkeypatch.setattr(v1_accounts_api.security, "read_rate_limited", lambda addr: True)
    resp = client.get("/v1/accounts/some-user-id/")
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "rate limit exceeded"


def test_v1_account_detail_not_found(client):
    resp = client.get("/v1/accounts/missing-user-id/")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "account not found"


def test_v1_accounts_happy_path(client):
    resp = client.get("/v1/accounts/", query_string={"q": "ada", "group": "wiki", "ordering": "recent"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["results"] == []
    assert body["source"] == "official"
