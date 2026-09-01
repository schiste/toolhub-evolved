# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001, I001, PLR2004, S101 - standalone operator-tool tests
"""Tests for external health collection and alert evaluation."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import check_production_health as monitor  # noqa: E402


METRICS = """\
# TYPE toolhub_process_uptime_seconds gauge
toolhub_process_uptime_seconds 120
toolhub_http_requests_total{method="GET",route="/",status_class="2xx"} 98
toolhub_http_requests_total{method="GET",route="/",status_class="5xx"} 2
toolhub_http_request_duration_seconds_bucket{le="0.05"} 50
toolhub_http_request_duration_seconds_bucket{le="0.5"} 94
toolhub_http_request_duration_seconds_bucket{le="1"} 100
toolhub_http_request_duration_seconds_bucket{le="+Inf"} 100
toolhub_http_request_duration_seconds_sum 10
toolhub_http_request_duration_seconds_count 100
"""


def test_metrics_parser_and_alert_thresholds_are_exact() -> None:
    summary = monitor.summarize_metrics(monitor.parse_metrics(METRICS))
    assert summary == {
        "requestTotal": 100,
        "serverErrorTotal": 2,
        "serverErrorShare": 0.02,
        "p95UpperBoundSeconds": 1.0,
        "processUptimeSeconds": 120.0,
    }
    alerts = monitor.evaluate(
        {
            "probes": {"live": True, "ready": True},
            "metrics": summary,
            "catalog": {"ageSeconds": 7199},
        }
    )
    assert [alert.code for alert in alerts] == ["http-5xx", "http-p95"]


def test_small_worker_sample_does_not_page_on_ratios() -> None:
    alerts = monitor.evaluate(
        {
            "probes": {"live": True, "ready": True},
            "metrics": {"requestTotal": 99, "serverErrorShare": 1.0, "p95UpperBoundSeconds": 5.0},
            "catalog": {"ageSeconds": 0},
        }
    )
    assert alerts == []


def test_exercise_covers_every_documented_rule(capsys: pytest.CaptureFixture[str]) -> None:
    assert monitor.main(["--exercise-alerts"]) == 0
    output = capsys.readouterr().out
    for code in ("liveness", "readiness", "http-5xx", "http-p95", "catalog-age"):
        assert f"Exercised {code}" in output


def test_collection_writes_a_machine_readable_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = {
        "/livez": (200, '{"ok":true}'),
        "/readyz": (200, '{"ok":true}'),
        "/metricsz": (200, METRICS.replace('status_class="5xx"} 2', 'status_class="5xx"} 0')),
        "/v1/catalog/health/": (200, '{"ageSeconds":60,"status":"ready"}'),
    }

    def fake_get(_base: str, path: str, *, timeout: float) -> tuple[int, str]:
        assert timeout == 10.0
        return payloads[path]

    monkeypatch.setattr(monitor, "_get", fake_get)
    output = tmp_path / "health.json"

    assert monitor.main(["--base-url", "https://example.test", "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["probes"] == {"live": True, "ready": True}
    assert report["metrics"]["requestTotal"] == 98
    assert report["catalog"]["ageSeconds"] == 60
