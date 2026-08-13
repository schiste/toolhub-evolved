# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for durable deployment stage diagnostics."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import deployment_diagnostics  # noqa: E402


def test_appends_structured_duration_metrics_and_failure_phase(tmp_path):
    output = tmp_path / "deployments.jsonl"
    metrics = tmp_path / "stage.out"
    metrics.write_text('projection-refresh: {"rows":42,"cacheHit":true}\n', encoding="utf-8")

    assert (
        deployment_diagnostics.main(
            [
                "--output",
                str(output),
                "--deployment",
                "abc123",
                "--stage",
                "projection-refresh",
                "--status",
                "completed",
                "--started",
                "100",
                "--finished",
                "102.25",
                "--metrics-file",
                str(metrics),
            ]
        )
        == 0
    )
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["durationMs"] == 2250
    assert row["metrics"] == {"rows": 42, "cacheHit": True}
    assert row["failurePhase"] is None
