# SPDX-License-Identifier: GPL-3.0-or-later
"""ProxyFix wiring: trust exactly the configured number of forwarding hops."""

import sys
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402


def test_register_wraps_wsgi_app_when_proxy_hops_configured(monkeypatch):
    monkeypatch.setenv("TOOLHUB_PROXYFIX_X_FOR", "1")
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    assert isinstance(application.wsgi_app, ProxyFix)


def test_register_leaves_wsgi_app_bare_without_proxy_hops(monkeypatch):
    monkeypatch.delenv("TOOLHUB_PROXYFIX_X_FOR", raising=False)
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    assert not isinstance(application.wsgi_app, ProxyFix)
