# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001, I001, PLR2004, S101 - standalone operator-tool tests
"""Tests for external health collection and alert evaluation."""

import json
import sys
import time
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


def test_label_parsing_stays_linear_on_a_malformed_label_set() -> None:
    """An unterminated label set must fail fast, not backtrack exponentially.

    /metricsz is fetched from production over the network, so the parser's input
    is not fully trusted. The earlier pattern let `[^"]` and `\\.` both match a
    backslash, so each added `\\!` doubled the ways to split the same text and a
    51-character string took over a second; the fix makes the split unique.
    """
    hostile = 'A="' + "\\!" * 24
    started = time.monotonic()
    assert monitor.LABEL_PATTERN.findall(hostile) == []
    assert time.monotonic() - started < 0.5

    escaped = r'route="/v1/say \"hi\"",method="GET"'
    assert monitor.LABEL_PATTERN.findall(escaped) == [("route", r"/v1/say \"hi\""), ("method", "GET")]


def _metrics(requests: int, errors: int, uptime: float | None = 600.0) -> dict:
    return {
        "requestTotal": requests,
        "serverErrorTotal": errors,
        "serverErrorShare": errors / requests if requests else 0.0,
        "p95UpperBoundSeconds": 0.05,
        "processUptimeSeconds": uptime,
    }


def test_a_long_clean_history_cannot_absorb_a_burst_of_errors() -> None:
    """The alert documents a 15-minute window, but /metricsz counts a lifetime.

    A worker that has served 100,000 good requests can return 300 5xx in one
    interval and still sit far below a cumulative 1%, so the lifetime ratio
    silently swallows exactly the incident the rule exists to catch.
    """
    previous = _metrics(100_000, 0)
    current = _metrics(100_300, 300)

    lifetime = monitor.evaluate(
        {"probes": {"live": True, "ready": True}, "metrics": current, "catalog": {"ageSeconds": 0}}
    )
    assert [alert.code for alert in lifetime] == []

    windowed = monitor.apply_window(current, previous)
    assert windowed["windowSource"] == "interval"
    assert windowed["windowRequestTotal"] == 300
    assert windowed["windowServerErrorShare"] == 1.0
    alerts = monitor.evaluate(
        {"probes": {"live": True, "ready": True}, "metrics": windowed, "catalog": {"ageSeconds": 0}}
    )
    assert [alert.code for alert in alerts] == ["http-5xx"]


def test_a_recovered_burst_stops_paging_once_the_interval_is_clean() -> None:
    """The mirror failure: a lifetime ratio keeps paging long after recovery."""
    previous = _metrics(200, 100)
    current = _metrics(1200, 100)

    windowed = monitor.apply_window(current, previous)

    assert windowed["windowRequestTotal"] == 1000
    assert windowed["windowServerErrorShare"] == 0.0
    assert (
        monitor.evaluate({"probes": {"live": True, "ready": True}, "metrics": windowed, "catalog": {"ageSeconds": 0}})
        == []
    )


def test_without_a_baseline_the_lifetime_totals_are_reported_unchanged() -> None:
    windowed = monitor.apply_window(_metrics(500, 10), None)

    assert windowed["windowSource"] == "lifetime"
    assert windowed["windowRequestTotal"] == 500
    assert windowed["windowServerErrorTotal"] == 10


def test_a_quiet_interval_reports_a_zero_share_rather_than_dividing_by_zero() -> None:
    previous = _metrics(500, 5)
    windowed = monitor.apply_window(_metrics(500, 5), previous)

    assert windowed["windowRequestTotal"] == 0
    assert windowed["windowServerErrorShare"] == 0.0


@pytest.mark.parametrize(
    ("previous", "current"),
    [
        (_metrics(900, 5), _metrics(100, 5)),  # requests went backwards
        (_metrics(900, 50), _metrics(1000, 5)),  # errors went backwards
        (
            _metrics(900, 5),
            _metrics(1000, 50),
        ),  # neither did, but uptime reset
    ],
)
def test_a_restart_reports_the_new_counters_whole(previous: dict, current: dict) -> None:
    """After a restart the counters start from zero, so the current totals *are*
    the interval; subtracting the pre-restart baseline would go negative."""
    if (
        current["requestTotal"] > previous["requestTotal"]
        and current["serverErrorTotal"] > previous["serverErrorTotal"]
    ):
        current = {**current, "processUptimeSeconds": 5.0}

    windowed = monitor.apply_window(current, previous)

    assert windowed["windowSource"] == "restart"
    assert windowed["windowRequestTotal"] == current["requestTotal"]
    assert windowed["windowServerErrorTotal"] == current["serverErrorTotal"]


def test_an_unreadable_or_foreign_baseline_is_treated_as_no_baseline(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert monitor.load_window_state(missing) is None

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert monitor.load_window_state(corrupt) is None

    foreign = tmp_path / "foreign.json"
    foreign.write_text("[1, 2, 3]", encoding="utf-8")
    assert monitor.load_window_state(foreign) is None


def test_a_scheduled_run_advances_the_baseline_it_measured_against(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {
        "/livez": (200, '{"ok":true}'),
        "/readyz": (200, '{"ok":true}'),
        "/metricsz": (200, METRICS),
        "/v1/catalog/health/": (200, '{"ageSeconds":60,"status":"ready"}'),
    }
    monkeypatch.setattr(monitor, "_get", lambda _base, path, *, timeout: payloads[path])
    state = tmp_path / "window.json"
    state.write_text(json.dumps({"requestTotal": 60, "serverErrorTotal": 2, "processUptimeSeconds": 60}), "utf-8")
    output = tmp_path / "health.json"

    monitor.main(["--base-url", "https://example.test", "--output", str(output), "--state", str(state)])

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["windowSource"] == "interval"
    assert report["metrics"]["windowRequestTotal"] == 40
    assert report["metrics"]["windowServerErrorTotal"] == 0
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "requestTotal": 100,
        "serverErrorTotal": 2,
        "processUptimeSeconds": 120.0,
    }


def test_a_failed_scrape_leaves_the_baseline_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving the zeroed defaults of a failed scrape would make the next interval
    look like the counters had jumped from nothing to the full lifetime total."""

    def fake_get(_base: str, path: str, *, timeout: float) -> tuple[int, str]:
        if path == "/metricsz":
            raise OSError("connection reset")
        return {"/livez": (200, '{"ok":true}'), "/readyz": (200, '{"ok":true}')}.get(path, (200, "{}"))

    monkeypatch.setattr(monitor, "_get", fake_get)
    state = tmp_path / "window.json"
    baseline = {"requestTotal": 100, "serverErrorTotal": 2, "processUptimeSeconds": 120.0}
    state.write_text(json.dumps(baseline), encoding="utf-8")

    monitor.main(["--base-url", "https://example.test", "--state", str(state)])

    assert json.loads(state.read_text(encoding="utf-8")) == baseline
