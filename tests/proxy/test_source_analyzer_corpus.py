# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the analyzer over a real repository and assert the report holds together.

Every other test in this suite feeds the analyzer files written to demonstrate
a rule. Those tests cannot disagree with the rule they illustrate: the input was
authored by whoever authored the expectation. This module supplies input nobody
wrote for it -- this repository's own checkout, several hundred tracked files of
ordinary Python, JavaScript, Markdown, YAML and shell -- and asserts the
properties the report must satisfy whatever it happens to find in there.

Nothing here pins a value. Values move as the repository moves and a test that
pinned them would be rewritten to match rather than read as a failure. The
assertions are invariants: the report is internally consistent, the evidence
traces back to real input, the publication gate is actually closed, and the same
input twice produces the same report.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "proxy"))

from backend.source_analysis_common import (  # noqa: E402
    CONFIDENCE_CAP,
    HEALTH_MIN_SCORING_CONFIDENCE,
    MAX_FILE_BYTES,
    MAX_FILES,
    PUBLICATION_TRUSTED_SOURCE_WEIGHT,
)
from backend.source_analyzer import analyze_source_files, order_sources_for_reading  # noqa: E402

FINDING_BUCKETS = (
    "projects",
    "apis",
    "accessRights",
    "authentication",
    "dependencies",
    "endpoints",
    "oauthScopes",
    "browserPermissions",
    "technology",
    "warnings",
)
# A corpus this small would not exercise the reading caps, and the reserve
# behaviour under contention is exactly what this module exists to observe.
MIN_CORPUS_FILES = 120


def _tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return [line for line in result.stdout.splitlines() if line]


def _read(paths: list[str]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for rel in paths:
        path = REPO_ROOT / rel
        try:
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                continue
            files.append({"path": rel, "content": path.read_text(errors="replace")})
        except OSError:
            continue
    return files


@pytest.fixture(scope="module")
def corpus() -> list[dict[str, str]]:
    tracked = _tracked_paths()
    if len(tracked) < MIN_CORPUS_FILES:
        pytest.skip("checkout too small to be a corpus")
    return _read(order_sources_for_reading(tracked, budget=MAX_FILES)[:MAX_FILES])


@pytest.fixture(scope="module")
def report(corpus: list[dict[str, str]]) -> dict:
    return analyze_source_files(corpus)


def _findings(report: dict) -> list[tuple[str, dict]]:
    return [(bucket, item) for bucket in FINDING_BUCKETS for item in report[bucket]]


def test_the_corpus_is_large_enough_to_contend_for_reading_slots(corpus):
    assert len(corpus) >= MIN_CORPUS_FILES // 2
    assert len({file["path"].split("/")[0] for file in corpus}) > 1


def test_every_bucket_and_section_is_present(report):
    for bucket in FINDING_BUCKETS:
        assert isinstance(report[bucket], list)
    for section in ("summary", "assessments", "healthCore", "suggestions"):
        assert section in report


def test_every_finding_carries_the_fields_its_consumers_read(report):
    required = (
        "value",
        "label",
        "kind",
        "category",
        "confidence",
        "maxSourceWeight",
        "fileCount",
        "reasons",
        "sourceClasses",
        "evidence",
    )
    findings = _findings(report)
    assert findings, "a repository this size should yield findings"
    for bucket, item in findings:
        missing = [field for field in required if field not in item]
        assert not missing, f"{bucket}/{item.get('value')} is missing {missing}"
        assert item["value"], f"{bucket} produced a finding with no value"
        assert item["reasons"], f"{bucket}/{item['value']} states no reason"


def test_confidence_and_weight_stay_inside_their_ranges(report):
    for bucket, item in _findings(report):
        where = f"{bucket}/{item['value']}"
        assert 0 < item["confidence"] <= CONFIDENCE_CAP, where
        assert 0 <= item["maxSourceWeight"] <= 1, where


def test_evidence_points_at_files_that_were_actually_supplied(report, corpus):
    supplied = {file["path"] for file in corpus}
    for bucket, item in _findings(report):
        for evidence in item["evidence"]:
            assert evidence["path"] in supplied, f"{bucket}/{item['value']} cites {evidence['path']}"
            assert evidence["line"] >= 1


def test_the_file_count_agrees_with_the_evidence_it_summarises(report):
    """Evidence is truncated per finding; fileCount is not, so it can only be larger."""
    for bucket, item in _findings(report):
        distinct = {evidence["path"] for evidence in item["evidence"]}
        assert item["fileCount"] >= len(distinct), f"{bucket}/{item['value']}"


def test_the_recorded_weight_is_the_best_weight_in_the_evidence(report):
    for bucket, item in _findings(report):
        for evidence in item["evidence"]:
            assert item["maxSourceWeight"] >= evidence["sourceWeight"] - 0.001, f"{bucket}/{item['value']}"


def test_nothing_uncorroborated_reaches_the_suggestion_patch(report):
    """The gate added for the seven published non-wikis, checked against real input."""
    patch = report["suggestions"]["toolinfoPatch"]
    by_bucket = {bucket: {item["value"]: item for item in report[bucket]} for bucket in FINDING_BUCKETS}
    for field, values in patch.items():
        for value in values if isinstance(values, list) else [values]:
            for bucket in FINDING_BUCKETS:
                item = by_bucket[bucket].get(value)
                if item is None:
                    continue
                corroborated = item["fileCount"] > 1 or item["maxSourceWeight"] >= PUBLICATION_TRUSTED_SOURCE_WEIGHT
                assert corroborated, f"{field}={value} was published on one soft mention"


def test_the_health_score_and_its_grade_describe_the_same_result(report):
    core = report["healthCore"]
    assert 0 <= core["score"] <= 100
    assert 0 <= core["confidence"] <= 1
    if core["confidence"] < HEALTH_MIN_SCORING_CONFIDENCE:
        assert core["grade"] == "unknown"
        return
    bands = (("strong", 85), ("good", 70), ("needs-attention", 50), ("high-risk", 0))
    expected = next(grade for grade, floor in bands if core["score"] >= floor)
    assert core["grade"] == expected


def test_the_composite_confidence_never_exceeds_the_dimensions_under_it(report):
    """A grade cannot be more believed than the evidence it was computed from."""
    core = report["healthCore"]
    scored = [item for item in core["dimensions"] if item["includedInScore"]]
    assert scored, "nothing was scored"
    assert core["confidence"] <= max(item["confidence"] for item in scored) + 0.001


def test_the_reserve_reaches_the_classes_that_lose_the_ranking(corpus):
    """Documentation, CI and tests rank below source and are read anyway."""
    seen = {file["path"] for file in corpus}
    assert any(path.startswith("docs/") or path.endswith(".md") for path in seen)
    assert any(path.startswith("tests/") for path in seen)


def test_the_same_corpus_twice_produces_the_same_report(corpus):
    assert json.dumps(analyze_source_files(corpus), sort_keys=True) == json.dumps(
        analyze_source_files(corpus), sort_keys=True
    )


def test_the_result_does_not_depend_on_the_order_the_files_arrive_in(corpus, report):
    shuffled = list(corpus)
    random.Random(20260824).shuffle(shuffled)
    assert analyze_source_files(shuffled)["suggestions"] == report["suggestions"]
