# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct-unit coverage for v1_source_analysis helpers not reached elsewhere.

The Flask endpoints in this blueprint are already covered end-to-end in
test_backend.py; these tests target the small pure/DB-touching helpers that
back them, which is cheaper than routing through the full HTTP surface.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, v1_source_analysis  # noqa: E402


def test_maintainer_context_from_summary_aggregates_activity_and_ages():
    summary = {
        "healthCounts": {"maintainers": 2, "activePeople": 1},
        "people": [
            "not-a-dict",
            {"activity": "not-a-dict-either"},
            {"activity": {"lastContributionAgeDays": 5, "recentContributionCount": 3}},
            {"activity": {"lastContributionAgeDays": -2, "recentContributionCount": 1}},
        ],
    }

    context = v1_source_analysis._maintainer_context_from_summary(summary)

    assert context["maintainerCount"] == 2
    assert context["activeMaintainerCount"] == 1
    assert context["recentActivityCount"] == 4
    # -2 is clamped to 0 before being considered for the minimum.
    assert context["lastActivityAgeDays"] == 0
    assert context["source"] == "evolved-people-index"


def test_maintainer_context_from_summary_returns_empty_without_people():
    assert v1_source_analysis._maintainer_context_from_summary({"people": []}) == {}


def test_source_repository_context_merges_evolved_maintainers_when_absent():
    db.configure("sqlite://")
    db.init_schema()

    merged = v1_source_analysis._source_repository_context("unclaimed-tool", {"existing": "context"})

    # No author claims exist for this tool, so the derived maintainer context
    # is empty and the original repository context is returned untouched --
    # but only after the database lookup path (sync_author_claim_edges,
    # activity refresh, public_tool_summary) actually ran.
    assert merged == {"existing": "context"}


def test_source_repository_context_short_circuits_without_a_tool_name():
    assert v1_source_analysis._source_repository_context(None, {"existing": "context"}) == {"existing": "context"}


def test_source_repository_context_short_circuits_on_non_dict_context():
    assert v1_source_analysis._source_repository_context("some-tool", "not-a-dict") == "not-a-dict"


def test_source_repository_context_short_circuits_when_maintainers_already_present():
    existing = {"maintainers": {"source": "caller-provided"}}
    assert v1_source_analysis._source_repository_context("some-tool", existing) is existing
