# SPDX-License-Identifier: GPL-3.0-or-later
"""Low-cardinality request correlation, health probes, and process metrics."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import uuid4

from flask import Blueprint, Flask, Response, current_app, g, jsonify, request
from sqlalchemy import text

from backend import db

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
HTTP_SERVICE_UNAVAILABLE = 503


@dataclass(frozen=True)
class MetricsSnapshot:
    """One lock-consistent view of this worker's bounded request counters."""

    uptime_seconds: float
    request_total: int
    duration_seconds: float
    latency_buckets: tuple[int, ...]
    routes: tuple[tuple[tuple[str, str, str], int], ...]


class RequestMetrics:
    """Thread-safe in-process counters with finite route and latency labels."""

    def __init__(self) -> None:
        """Create an empty metrics collector."""
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        """Reset counters; used by tests and naturally by every worker start."""
        with self._lock:
            self._started_at = monotonic()
            self._request_total = 0
            self._duration_seconds = 0.0
            self._latency_buckets = [0 for _bucket in LATENCY_BUCKETS]
            self._routes: Counter[tuple[str, str, str]] = Counter()

    def observe(self, method: str, route: str, status: int, duration_seconds: float) -> None:
        """Record one completed request under normalized finite labels."""
        bounded_duration = max(0.0, duration_seconds)
        status_class = f"{status // 100}xx"
        with self._lock:
            self._request_total += 1
            self._duration_seconds += bounded_duration
            self._routes[(method, route, status_class)] += 1
            for index, upper_bound in enumerate(LATENCY_BUCKETS):
                if bounded_duration <= upper_bound:
                    self._latency_buckets[index] += 1

    def snapshot(self) -> MetricsSnapshot:
        """Return a deterministic copy suitable for rendering without the lock."""
        with self._lock:
            return MetricsSnapshot(
                uptime_seconds=max(0.0, monotonic() - self._started_at),
                request_total=self._request_total,
                duration_seconds=self._duration_seconds,
                latency_buckets=tuple(self._latency_buckets),
                routes=tuple(sorted(self._routes.items())),
            )


metrics = RequestMetrics()
observability_bp = Blueprint("observability", __name__)


def reset_metrics() -> None:
    """Reset the current worker's metrics (test isolation)."""
    metrics.reset()


def _request_id() -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid4().hex


def _route_label() -> str:
    return request.url_rule.rule if request.url_rule is not None else "<unmatched>"


def begin_request() -> None:
    """Attach correlation and timing state before routing a request."""
    g.toolhub_request_id = _request_id()
    g.toolhub_observability_start = monotonic()


def complete_request(response: Response) -> Response:
    """Publish correlation, counters, and a normalized completion log."""
    duration = max(0.0, monotonic() - g.toolhub_observability_start)
    route = _route_label()
    metrics.observe(request.method, route, response.status_code, duration)
    response.headers[REQUEST_ID_HEADER] = g.toolhub_request_id
    current_app.logger.info(
        "request_complete request_id=%s method=%s route=%s status=%d duration_ms=%.1f",
        g.toolhub_request_id,
        request.method,
        route,
        response.status_code,
        duration * 1000,
    )
    return response


def _prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metrics(snapshot: MetricsSnapshot) -> str:
    """Render one worker snapshot in Prometheus text exposition format."""
    lines = [
        "# HELP toolhub_process_uptime_seconds Worker uptime in seconds.",
        "# TYPE toolhub_process_uptime_seconds gauge",
        f"toolhub_process_uptime_seconds {snapshot.uptime_seconds:.6f}",
        "# HELP toolhub_http_requests_total Completed HTTP requests by normalized route.",
        "# TYPE toolhub_http_requests_total counter",
    ]
    for (method, route, status_class), count in snapshot.routes:
        method_label, route_label, status_label = (_prometheus_label(value) for value in (method, route, status_class))
        lines.append(
            f'toolhub_http_requests_total{{method="{method_label}",route="{route_label}",'
            f'status_class="{status_label}"}} {count}'
        )
    lines.extend(
        [
            "# HELP toolhub_http_request_duration_seconds Completed request duration.",
            "# TYPE toolhub_http_request_duration_seconds histogram",
        ]
    )
    for upper_bound, count in zip(LATENCY_BUCKETS, snapshot.latency_buckets, strict=True):
        lines.append(f'toolhub_http_request_duration_seconds_bucket{{le="{upper_bound:g}"}} {count}')
    lines.extend(
        [
            f'toolhub_http_request_duration_seconds_bucket{{le="+Inf"}} {snapshot.request_total}',
            f"toolhub_http_request_duration_seconds_sum {snapshot.duration_seconds:.6f}",
            f"toolhub_http_request_duration_seconds_count {snapshot.request_total}",
        ]
    )
    return "\n".join(lines) + "\n"


def _database_ready() -> bool:
    try:
        with db.session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - readiness deliberately folds all DB failures together
        return False
    return True


@observability_bp.get("/livez")
def livez() -> Response:
    """Process liveness only; never waits for a dependency."""
    return jsonify({"ok": True, "status": "alive"})


@observability_bp.get("/readyz")
def readyz() -> Response:
    """Traffic readiness, including database reachability."""
    ready = _database_ready()
    response = jsonify(
        {
            "ok": ready,
            "status": "ready" if ready else "unready",
            "checks": {"database": "ok" if ready else "unavailable"},
        }
    )
    response.status_code = 200 if ready else HTTP_SERVICE_UNAVAILABLE
    return response


@observability_bp.get("/metricsz")
def metricsz() -> Response:
    """Expose bounded, content-free metrics for this worker process."""
    response = Response(render_metrics(metrics.snapshot()), content_type=METRICS_CONTENT_TYPE)
    response.headers["Cache-Control"] = "no-store"
    return response


def register(app: Flask) -> None:
    """Register request hooks and public observability endpoints."""
    app.before_request(begin_request)
    app.after_request(complete_request)
    app.register_blueprint(observability_bp)
