# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: S310, T201 - operator URL reads and annotations are the interface
"""Probe production health and evaluate the documented operational alerts."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://toolhub-evolved.toolforge.org"
MIN_METRIC_SAMPLE = 100
MAX_5XX_SHARE = 0.01
MAX_P95_SECONDS = 0.5
MAX_CATALOG_AGE_SECONDS = 2 * 60 * 60
HTTP_OK = 200
SAMPLE_PATTERN = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+(?P<value>\S+)$")
# Both alternatives must not match the same first character: with `[^"]` able to
# match a backslash that `\\.` also starts on, every added `\\!` doubles the ways
# to split the same text, and an unterminated label set backtracks exponentially.
# Excluding the backslash from the negated class makes the split unique.
LABEL_PATTERN = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Sample:
    """One numeric Prometheus sample and its bounded labels."""

    name: str
    labels: dict[str, str]
    value: float


@dataclass(frozen=True)
class Alert:
    """One operator-facing threshold violation."""

    code: str
    message: str


def parse_metrics(body: str) -> list[Sample]:
    """Parse the bounded Prometheus text emitted by this service."""
    samples = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = SAMPLE_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(line[:120])
        labels = dict(LABEL_PATTERN.findall(match.group("labels") or ""))
        samples.append(Sample(match.group("name"), labels, float(match.group("value"))))
    return samples


def summarize_metrics(samples: list[Sample]) -> dict[str, float | int | None]:
    """Reduce one worker scrape to the SLO signals used by alert rules."""
    route_samples = [sample for sample in samples if sample.name == "toolhub_http_requests_total"]
    request_total = int(sum(sample.value for sample in route_samples))
    server_errors = int(sum(sample.value for sample in route_samples if sample.labels.get("status_class") == "5xx"))
    count = next(
        (sample.value for sample in samples if sample.name == "toolhub_http_request_duration_seconds_count"),
        0.0,
    )
    target = count * 0.95
    buckets = []
    for sample in samples:
        if sample.name != "toolhub_http_request_duration_seconds_bucket":
            continue
        raw_bound = sample.labels.get("le", "+Inf")
        bound = math.inf if raw_bound == "+Inf" else float(raw_bound)
        buckets.append((bound, sample.value))
    p95 = next((bound for bound, cumulative in sorted(buckets) if count and cumulative >= target), None)
    uptime = next(
        (sample.value for sample in samples if sample.name == "toolhub_process_uptime_seconds"),
        None,
    )
    return {
        "requestTotal": request_total,
        "serverErrorTotal": server_errors,
        "serverErrorShare": server_errors / request_total if request_total else 0.0,
        "p95UpperBoundSeconds": p95,
        "processUptimeSeconds": uptime,
    }


def evaluate(report: dict[str, Any]) -> list[Alert]:
    """Evaluate immediate sentinels and sampled counterparts of documented SLOs."""
    alerts = []
    if not report["probes"]["live"]:
        alerts.append(Alert("liveness", "/livez did not return a healthy response"))
    if not report["probes"]["ready"]:
        alerts.append(Alert("readiness", "/readyz did not return a healthy response"))
    metrics = report["metrics"]
    if metrics["requestTotal"] >= MIN_METRIC_SAMPLE and metrics["serverErrorShare"] >= MAX_5XX_SHARE:
        alerts.append(Alert("http-5xx", f"sampled HTTP 5xx share is {metrics['serverErrorShare']:.2%} (limit < 1%)"))
    p95 = metrics["p95UpperBoundSeconds"]
    if metrics["requestTotal"] >= MIN_METRIC_SAMPLE and p95 is not None and p95 > MAX_P95_SECONDS:
        alerts.append(Alert("http-p95", f"sampled HTTP p95 exceeds {MAX_P95_SECONDS:g}s (bucket {p95:g}s)"))
    age = report["catalog"].get("ageSeconds")
    if age is None or age >= MAX_CATALOG_AGE_SECONDS:
        rendered = "unknown" if age is None else f"{age}s"
        alerts.append(Alert("catalog-age", f"published catalog age is {rendered} (limit < 7200s)"))
    return alerts


def _get(base_url: str, path: str, *, timeout: float) -> tuple[int, str]:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Accept": "application/json,text/plain", "User-Agent": "toolhub-evolved-monitor/1"},
    )
    with urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def _require_ok(status: int) -> None:
    if status != HTTP_OK:
        raise ValueError(str(status))


def collect(base_url: str, *, timeout: float) -> dict[str, Any]:
    """Collect live production probes while retaining partial failure details."""
    report: dict[str, Any] = {
        "checkedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "baseUrl": base_url,
        "probes": {"live": False, "ready": False},
        "metrics": {
            "requestTotal": 0,
            "serverErrorTotal": 0,
            "serverErrorShare": 0.0,
            "p95UpperBoundSeconds": None,
            "processUptimeSeconds": None,
        },
        "catalog": {"ageSeconds": None},
        "collectionErrors": [],
    }
    for name, path in (("live", "/livez"), ("ready", "/readyz")):
        try:
            status, body = _get(base_url, path, timeout=timeout)
            payload = json.loads(body)
            report["probes"][name] = status == HTTP_OK and payload.get("ok") is True
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            report["collectionErrors"].append(f"{path}: {error}")
    try:
        status, body = _get(base_url, "/metricsz", timeout=timeout)
        _require_ok(status)
        report["metrics"] = summarize_metrics(parse_metrics(body))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        report["collectionErrors"].append(f"/metricsz: {error}")
        report["probes"]["ready"] = False
    try:
        status, body = _get(base_url, "/v1/catalog/health/", timeout=timeout)
        payload = json.loads(body)
        _require_ok(status)
        report["catalog"] = {"ageSeconds": payload.get("ageSeconds"), "status": payload.get("status")}
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as error:
        report["collectionErrors"].append(f"/v1/catalog/health/: {error}")
    return report


def exercise_alerts() -> list[Alert]:
    """Evaluate every rule against one deterministic synthetic incident."""
    report = {
        "probes": {"live": False, "ready": False},
        "metrics": {
            "requestTotal": 100,
            "serverErrorTotal": 2,
            "serverErrorShare": 0.02,
            "p95UpperBoundSeconds": 1.0,
        },
        "catalog": {"ageSeconds": MAX_CATALOG_AGE_SECONDS},
    }
    return evaluate(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--exercise-alerts", action="store_true")
    args = parser.parse_args(argv)
    if args.exercise_alerts:
        alerts = exercise_alerts()
        expected = {"liveness", "readiness", "http-5xx", "http-p95", "catalog-age"}
        detected = {alert.code for alert in alerts}
        for alert in alerts:
            print(f"::notice title=Exercised {alert.code}::{alert.message}")
        return 0 if detected == expected else 1

    report = collect(args.base_url, timeout=args.timeout)
    alerts = evaluate(report)
    report["alerts"] = [asdict(alert) for alert in alerts]
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    for error in report["collectionErrors"]:
        print(f"::error title=Monitoring collection failed::{error}", file=sys.stderr)
    for alert in alerts:
        print(f"::error title={alert.code}::{alert.message}", file=sys.stderr)
    return 1 if report["collectionErrors"] or alerts else 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
