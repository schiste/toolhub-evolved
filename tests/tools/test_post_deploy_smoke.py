# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract tests for the production post-deploy smoke probe."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import post_deploy_smoke as smoke  # noqa: E402


def encoded(value):
    return json.dumps(value).encode()


def test_readiness_requires_the_database_backed_health_contract():
    probe = smoke.PROBES[0]
    assert smoke.validate_probe(probe, 200, encoded({"ok": True})) == {"name": "readiness", "status": 200}
    with pytest.raises(ValueError, match="not healthy"):
        smoke.validate_probe(probe, 503, encoded({"ok": False}))


def test_catalog_requires_a_nonempty_local_generation():
    probe = smoke.PROBES[1]
    healthy = {
        "source": "local_replica",
        "status": "idle",
        "recordCount": 42,
        "generation": 7,
        "stale": False,
        "upstreamOnRequest": False,
    }
    assert smoke.validate_probe(probe, 200, encoded(healthy))["status"] == 200
    with pytest.raises(ValueError, match="completed generation"):
        smoke.validate_probe(probe, 200, encoded({**healthy, "recordCount": 0, "status": "unavailable"}))
    with pytest.raises(ValueError, match="request-safe local replica"):
        smoke.validate_probe(probe, 200, encoded({**healthy, "upstreamOnRequest": True}))


def test_capabilities_require_auth_and_write_availability_to_agree():
    probe = smoke.PROBES[2]
    payload = {"oauth": True, "officialWrites": True, "devLogin": False, "issueReports": True}
    assert smoke.validate_probe(probe, 200, encoded(payload))["name"] == "capabilities"
    with pytest.raises(ValueError, match="disagrees"):
        smoke.validate_probe(probe, 200, encoded({**payload, "officialWrites": False}))


def test_write_probe_accepts_only_an_auth_or_csrf_refusal():
    probe = smoke.PROBES[3]
    assert smoke.validate_probe(probe, 403, encoded({"error": "forbidden"}))["name"] == "write-guard"
    with pytest.raises(ValueError, match="was not rejected"):
        smoke.validate_probe(probe, 200, encoded({"ok": True}))


def test_every_probe_requires_a_json_object():
    with pytest.raises(ValueError, match="did not return JSON"):
        smoke.validate_probe(smoke.PROBES[0], 200, b"<html>")
    with pytest.raises(ValueError, match="expected an object"):
        smoke.validate_probe(smoke.PROBES[0], 200, b"[]")


def test_run_fetches_and_validates_every_probe(monkeypatch):
    payloads = {
        "readiness": (200, encoded({"ok": True})),
        "catalog": (
            200,
            encoded(
                {
                    "source": "local_replica",
                    "status": "idle",
                    "recordCount": 1,
                    "generation": 1,
                    "stale": False,
                    "upstreamOnRequest": False,
                }
            ),
        ),
        "capabilities": (
            200,
            encoded({"oauth": False, "officialWrites": False, "devLogin": False, "issueReports": False}),
        ),
        "write-guard": (401, encoded({"error": "authentication required"})),
    }
    monkeypatch.setattr(smoke, "fetch", lambda probe, _base, _timeout: payloads[probe.name])

    assert [row["name"] for row in smoke.run("https://example.test", 1)] == [probe.name for probe in smoke.PROBES]
