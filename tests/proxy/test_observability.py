# SPDX-License-Identifier: GPL-3.0-or-later
"""Request-correlation, health, and process-metrics contracts."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import observability  # noqa: E402


@pytest.fixture
def app() -> Flask:
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    observability.reset_metrics()
    return application


@pytest.fixture
def client(app: Flask):
    return app.test_client()


def test_request_ids_are_preserved_or_safely_replaced(client, monkeypatch, caplog) -> None:
    monkeypatch.setattr(observability, "uuid4", lambda: SimpleNamespace(hex="generated-request-id"))
    caplog.set_level(logging.INFO)

    supplied = client.get("/livez", headers={"X-Request-ID": "edge.valid:123"})
    generated = client.get("/missing", headers={"X-Request-ID": "bad request id"})

    assert supplied.headers["X-Request-ID"] == "edge.valid:123"
    assert generated.headers["X-Request-ID"] == "generated-request-id"
    assert "request_id=edge.valid:123 method=GET route=/livez status=200" in caplog.text
    assert "route=<unmatched> status=404" in caplog.text


def test_liveness_never_waits_for_database_but_readiness_does(client, monkeypatch) -> None:
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.get_json() == {"ok": True, "status": "ready", "checks": {"database": "ok"}}

    monkeypatch.setattr(observability, "_database_ready", lambda: False)
    assert client.get("/livez").get_json() == {"ok": True, "status": "alive"}
    unavailable = client.get("/readyz")
    assert unavailable.status_code == 503
    assert unavailable.get_json() == {
        "ok": False,
        "status": "unready",
        "checks": {"database": "unavailable"},
    }


def test_public_observability_surface_is_exact_and_read_only(app) -> None:
    routes = {
        rule.rule: sorted(rule.methods - {"HEAD", "OPTIONS"})
        for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith("observability.")
    }
    assert routes == {"/livez": ["GET"], "/metricsz": ["GET"], "/readyz": ["GET"]}


def test_database_probe_folds_dependency_failures_into_unready(monkeypatch) -> None:
    def fail_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(observability.db, "session_scope", fail_session)
    assert observability._database_ready() is False  # noqa: SLF001 - focused health-contract test


def test_metrics_are_bounded_normalized_and_prometheus_compatible(client) -> None:
    empty = observability.render_metrics(observability.metrics.snapshot())
    assert "toolhub_http_request_duration_seconds_count 0" in empty

    observability.metrics.observe('G"ET', "/odd\\route\n", 200, -1)
    observability.metrics.observe("POST", "/slow", 503, 10)
    snapshot = observability.metrics.snapshot()
    assert snapshot.request_total == 2
    assert snapshot.duration_seconds == 10
    assert snapshot.latency_buckets == (1, 1, 1, 1, 1, 1, 1)

    response = client.get("/metricsz")
    body = response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.mimetype == "text/plain"
    assert 'method="G\\"ET",route="/odd\\\\route\\n",status_class="2xx"} 1' in body
    assert 'method="POST",route="/slow",status_class="5xx"} 1' in body
    assert 'toolhub_http_request_duration_seconds_bucket{le="+Inf"} 2' in body
    assert "toolhub_http_request_duration_seconds_sum 10.000000" in body

    observability.reset_metrics()
    assert observability.metrics.snapshot().request_total == 0
