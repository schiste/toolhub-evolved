# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify the public production contract before a deployment is promoted."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

HTTP_OK = 200
EXPECTED_WRITE_REFUSALS = {401, 403}


@dataclass(frozen=True)
class Probe:
    """One non-mutating production request and its response contract."""

    name: str
    path: str
    method: str = "GET"
    body: bytes | None = None


PROBES = (
    Probe("readiness", "/healthz"),
    Probe("catalog", "/v1/catalog/health/"),
    Probe("capabilities", "/v1/config/"),
    # An anonymous, CSRF-less write attempt must be rejected before payload
    # validation or upstream I/O. This proves the write route and its guard are
    # both live without changing production data.
    Probe("write-guard", "/v1/write/tools/", method="POST", body=b"{}"),
)


def _json_object(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} did not return JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} returned {type(value).__name__}, expected an object")
    return value


def validate_probe(probe: Probe, status: int, raw: bytes) -> dict[str, Any]:
    """Validate one response and return its bounded diagnostic summary."""
    payload = _json_object(raw, probe.name)
    if probe.name == "readiness":
        if status != HTTP_OK or payload.get("ok") is not True:
            raise ValueError(f"readiness is not healthy (HTTP {status})")
    elif probe.name == "catalog":
        required = {"source", "status", "recordCount", "generation", "stale", "upstreamOnRequest"}
        missing = sorted(required - payload.keys())
        if status != HTTP_OK or missing:
            raise ValueError(f"catalog health contract is incomplete (HTTP {status}, missing={missing})")
        if payload["source"] != "local_replica" or payload["upstreamOnRequest"] is not False:
            raise ValueError("catalog health does not describe the request-safe local replica")
        if payload["status"] in {"failed", "unavailable"} or int(payload["recordCount"] or 0) <= 0:
            raise ValueError(
                f"catalog replica is not serving a completed generation "
                f"(status={payload['status']!r}, records={payload['recordCount']!r})"
            )
    elif probe.name == "capabilities":
        required = {"oauth", "officialWrites", "devLogin", "issueReports"}
        missing = sorted(required - payload.keys())
        if status != HTTP_OK or missing:
            raise ValueError(f"capability contract is incomplete (HTTP {status}, missing={missing})")
        if payload["officialWrites"] is not payload["oauth"]:
            raise ValueError("official write availability disagrees with OAuth availability")
    elif probe.name == "write-guard":
        if status not in EXPECTED_WRITE_REFUSALS:
            raise ValueError(f"anonymous write was not rejected before mutation (HTTP {status})")
    return {"name": probe.name, "status": status}


def fetch(probe: Probe, base_url: str, timeout: float) -> tuple[int, bytes]:
    """Perform one probe while preserving expected HTTP error responses."""
    request = Request(
        urljoin(base_url.rstrip("/") + "/", probe.path.lstrip("/")),
        data=probe.body,
        method=probe.method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied deployment URL
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def run(base_url: str, timeout: float) -> list[dict[str, Any]]:
    """Run the complete smoke contract, raising on the first unsafe response."""
    return [validate_probe(probe, *fetch(probe, base_url, timeout)) for probe in PROBES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    try:
        results = run(args.base_url, args.timeout)
    except (OSError, ValueError) as exc:
        print(f"post-deploy smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "baseUrl": args.base_url, "probes": results}, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
