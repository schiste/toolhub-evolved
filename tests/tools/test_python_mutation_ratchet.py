# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001, PLR2004, S101 - standalone policy-checker tests
"""Tests for the backend mutation-score ratchet."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import python_mutation_ratchet as ratchet  # noqa: E402, I001


POLICY = {
    "minimumScore": 75,
    "maximumNoTests": 0,
    "maximumSuspicious": 0,
    "maximumSegfault": 0,
    "maximumInterrupted": 0,
}


def test_mutation_score_counts_timeouts_as_caught() -> None:
    assert ratchet.mutation_score({"killed": 7, "timeout": 1, "survived": 2}) == 80


def test_mutation_score_is_complete_when_no_mutant_survived() -> None:
    assert ratchet.mutation_score({"killed": 0, "survived": 0}) == 100


def test_ratchet_reports_score_and_result_quality_regressions() -> None:
    stats = {
        "killed": 5,
        "timeout": 0,
        "survived": 5,
        "no_tests": 2,
        "suspicious": 1,
        "segfault": 0,
        "check_was_interrupted_by_user": 0,
    }
    assert ratchet.violations(stats, POLICY) == [
        "score 50.00% is below floor 75.00%",
        "no_tests 2 exceeds maximum 0",
        "suspicious 1 exceeds maximum 0",
    ]


def test_ratchet_accepts_a_clean_result_at_the_floor() -> None:
    stats = {"killed": 3, "timeout": 0, "survived": 1, "no_tests": 0}
    assert ratchet.violations(stats, POLICY) == []


def test_area_stats_classifies_critical_modules(tmp_path: Path) -> None:
    modules = {
        "authz": [1, 0],
        "security": [1, -24],
        "token_crypto": [0, -6],
        "outbound": [1, 1, 0],
        "sync": [1],
        "v1_write": [0],
        "inference_enrichment": [1],
        "source_analysis_assessments": [1, 0],
    }
    for module, exit_codes in modules.items():
        (tmp_path / f"{module}.py.meta").write_text(
            json.dumps({"exit_code_by_key": {str(index): code for index, code in enumerate(exit_codes)}}),
            encoding="utf-8",
        )

    areas = ratchet.area_stats(tmp_path)
    assert areas["authentication"] == {
        "killed": 2,
        "timeout": 1,
        "survived": 2,
        "infrastructure": 1,
        "score": 60.0,
    }
    assert areas["outboundIo"] == {
        "killed": 2,
        "timeout": 0,
        "survived": 1,
        "infrastructure": 0,
        "score": 200 / 3,
    }
    assert areas["dataIntegrity"] == {
        "killed": 3,
        "timeout": 0,
        "survived": 2,
        "infrastructure": 0,
        "score": 60.0,
    }
    assert "| authentication | 60.00% | 2 | 1 | 2 | 1 |" in ratchet.markdown_summary(62.5, {"survived": 5}, areas)
