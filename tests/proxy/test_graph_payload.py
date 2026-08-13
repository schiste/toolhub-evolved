# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend.graph_payload's private helpers.

tests/proxy/test_backend.py already exercises graph_payload.build()/payload()
end-to-end (including the shared/L1 cache machinery, which needs a DB). This
file targets the pure helper functions directly so it stays self-contained
and DB-free: it closes branch/line gaps in term extraction, cosine scoring,
kNN edge building (dense and sparse), community detection, and facet/group
bucketing that the end-to-end tests don't happen to hit.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import graph_payload  # noqa: E402


# ---------------------------------------------------------------------------
# _localized_text: dict-shaped Toolhub title values (lines 95-104)
# ---------------------------------------------------------------------------


def test_localized_text_returns_english_when_present():
    assert graph_payload._localized_text({"en": "  English Title  "}) == "English Title"


def test_localized_text_falls_through_to_mul_when_en_missing():
    assert graph_payload._localized_text({"fr": "", "mul": "Multi Title"}) == "Multi Title"


def test_localized_text_falls_back_to_any_language_value():
    assert graph_payload._localized_text({"de": "German Title"}) == "German Title"


def test_localized_text_returns_empty_when_all_dict_values_blank():
    assert graph_payload._localized_text({"en": "", "mul": "", "fr": "   "}) == ""


def test_localized_text_returns_empty_for_empty_dict():
    assert graph_payload._localized_text({}) == ""


def test_localized_text_returns_empty_for_non_string_non_dict():
    assert graph_payload._localized_text(None) == ""
    assert graph_payload._localized_text(123) == ""


# ---------------------------------------------------------------------------
# _terms: skip-empty-term branches for tasks/keywords/audiences and for_wikis
# (lines 127->125, 131, 133->129, 137)
# ---------------------------------------------------------------------------


def test_terms_skips_separator_only_values_and_extracts_wiki_and_type():
    record = {
        "tasks": ["---"],  # termifies to "" -> skipped (127->125)
        "keywords": ["Upload images"],
        "audiences": [],
        "for_wikis": ["*", "___", "commons.wikimedia.org"],  # "*" continues (131); "___" -> "" skipped (133->129)
        "tool_type": "Bot",
    }

    entries = graph_payload._terms(record)

    assert ("keyword", "upload images", graph_payload.TERM_WEIGHTS["keyword"]) in entries
    assert ("wiki", "commons wikimedia org", graph_payload.TERM_WEIGHTS["wiki"]) in entries
    assert ("type", "bot", graph_payload.TERM_WEIGHTS["type"]) in entries
    assert not any(kind == "task" for kind, _term, _weight in entries)
    assert len([e for e in entries if e[0] == "wiki"]) == 1


def test_terms_returns_empty_for_blank_signal_fields():
    record = {"keywords": ["---"], "tasks": ["..."], "audiences": ["///"], "for_wikis": ["*"]}
    assert graph_payload._terms(record) == []


# ---------------------------------------------------------------------------
# _cosine: empty-vector and disjoint-vector short circuits (lines 163, 167)
# ---------------------------------------------------------------------------


def test_cosine_returns_zero_for_empty_vectors():
    assert graph_payload._cosine({}, {"a:x": 1.0}) == 0.0
    assert graph_payload._cosine({"a:x": 1.0}, {}) == 0.0
    assert graph_payload._cosine({}, {}) == 0.0


def test_cosine_returns_zero_for_disjoint_nonempty_vectors():
    assert graph_payload._cosine({"a:x": 1.0}, {"a:y": 1.0}) == 0.0


def test_cosine_returns_positive_for_overlapping_vectors():
    assert graph_payload._cosine({"a:x": 1.0}, {"a:x": 1.0}) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _knn_edges: non-positive-weight skip branch (line 185->181)
# ---------------------------------------------------------------------------


def test_knn_edges_skips_zero_weight_pairs():
    names = ["a", "b", "c"]
    vectors = {"a": {"x": 1.0}, "b": {"y": 1.0}, "c": {"x": 1.0}}

    edges = graph_payload._knn_edges(names, vectors)

    pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert ("a", "b") not in pairs
    assert ("a", "c") in pairs


# ---------------------------------------------------------------------------
# _sparse_knn_edges: whole function was uncovered (lines 199-221)
# ---------------------------------------------------------------------------


def test_sparse_knn_edges_matches_dense_edges_and_isolates_disjoint_nodes():
    names = ["a", "b", "c", "d"]
    vectors = {
        "a": {"t:1": 1.0, "t:2": 1.0},
        "b": {"t:1": 1.0},
        "c": {"t:2": 1.0},
        "d": {"t:3": 1.0},  # shares no term with anyone -> no candidates, no edges
    }

    sparse = graph_payload._sparse_knn_edges(names, vectors)
    dense = graph_payload._knn_edges(names, vectors)

    assert sparse == dense
    assert not any("d" in (edge["source"], edge["target"]) for edge in sparse)
    pairs = {(edge["source"], edge["target"]) for edge in sparse}
    assert ("a", "b") in pairs
    assert ("a", "c") in pairs


# ---------------------------------------------------------------------------
# _detect_communities: unknown-node edge skip (line 234) and the
# loop-exhausted-without-converging path (line 238->255)
# ---------------------------------------------------------------------------


def test_detect_communities_skips_edges_referencing_unknown_nodes():
    labels = graph_payload._detect_communities(
        ["a", "b"],
        [
            {"source": "a", "target": "unknown", "weight": 1.0},
            {"source": "a", "target": "b", "weight": 1.0},
        ],
    )

    assert labels["a"] == labels["b"]


def test_detect_communities_runs_the_full_pass_budget_without_early_convergence():
    # Found by brute-force search over random weighted graphs (verified with a
    # line tracer): this 14-node, 30-edge graph keeps reassigning at least one
    # label on every one of the 8 allowed passes, so the `for _pass in
    # range(8)` loop never hits `break` (line 254) and instead falls through
    # the exhausted loop condition straight to `return labels` (238->255).
    names = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n"]
    edges = [
        {"source": "a", "target": "h", "weight": 2.0},
        {"source": "a", "target": "i", "weight": 3.0},
        {"source": "a", "target": "k", "weight": 1.5},
        {"source": "a", "target": "l", "weight": 2.5},
        {"source": "a", "target": "n", "weight": 2.0},
        {"source": "b", "target": "d", "weight": 2.0},
        {"source": "b", "target": "f", "weight": 0.7},
        {"source": "b", "target": "h", "weight": 0.7},
        {"source": "b", "target": "i", "weight": 0.7},
        {"source": "c", "target": "d", "weight": 2.5},
        {"source": "c", "target": "h", "weight": 0.1},
        {"source": "d", "target": "j", "weight": 1.3},
        {"source": "d", "target": "k", "weight": 1.3},
        {"source": "e", "target": "g", "weight": 2.5},
        {"source": "e", "target": "h", "weight": 1.5},
        {"source": "e", "target": "m", "weight": 0.7},
        {"source": "e", "target": "n", "weight": 2.5},
        {"source": "f", "target": "j", "weight": 1.5},
        {"source": "f", "target": "m", "weight": 1.3},
        {"source": "g", "target": "h", "weight": 2.0},
        {"source": "g", "target": "j", "weight": 1.3},
        {"source": "g", "target": "l", "weight": 3.0},
        {"source": "g", "target": "m", "weight": 0.2},
        {"source": "h", "target": "l", "weight": 0.1},
        {"source": "h", "target": "m", "weight": 0.7},
        {"source": "h", "target": "n", "weight": 2.5},
        {"source": "i", "target": "j", "weight": 0.5},
        {"source": "i", "target": "m", "weight": 0.7},
        {"source": "j", "target": "m", "weight": 1.5},
        {"source": "k", "target": "m", "weight": 1.3},
    ]

    labels = graph_payload._detect_communities(names, edges)

    assert labels == {name: "g" for name in names}


# ---------------------------------------------------------------------------
# _ranked_terms: defensive skip of a falsy human label (line 265->263).
#
# In production this branch is unreachable: every `raw` value here comes from
# _string_list(), which only ever yields already-stripped, non-empty strings,
# and _human_label() falls back to returning its input verbatim (`or value`)
# whenever splitting empties it out -- so a non-empty `raw` can never produce
# a falsy `label`. The guard is still real code, so it's exercised here by
# monkeypatching the collaborator to force the case it defends against.
# ---------------------------------------------------------------------------


def test_ranked_terms_skips_falsy_human_labels(monkeypatch):
    monkeypatch.setattr(graph_payload, "_human_label", lambda value: "" if value == "skip-me" else value)
    items = [{"record": {"keywords": ["skip-me", "keep-me"]}}]

    ranked = graph_payload._ranked_terms(items)

    assert ranked == ["keep-me"]


# ---------------------------------------------------------------------------
# _communities: fallback "Cluster N" label when a group has no ranked terms
# (line 287)
# ---------------------------------------------------------------------------


def test_communities_falls_back_to_cluster_label_without_ranked_terms():
    selected = [{"name": "solo", "record": {}}]
    labels = {"solo": "solo"}

    _node_communities, meta = graph_payload._communities(selected, labels)

    assert meta == [{"id": 0, "label": "Cluster 1", "size": 1}]


# ---------------------------------------------------------------------------
# _facet_value: blank/wildcard rejection (line 312)
# ---------------------------------------------------------------------------


def test_facet_value_rejects_blank_and_wildcard_input():
    assert graph_payload._facet_value("") is None
    assert graph_payload._facet_value("   ") is None
    assert graph_payload._facet_value("*") is None


def test_facet_value_normalizes_and_labels_real_values():
    assert graph_payload._facet_value("Bots") == ("bots", "Bots")


# ---------------------------------------------------------------------------
# _project_value: passthrough for values with no alias (line 331)
# ---------------------------------------------------------------------------


def test_project_value_passes_through_unaliased_project_names():
    assert graph_payload._project_value("Random Wiki Project") == "Random Wiki Project"


# ---------------------------------------------------------------------------
# _group_data: "other" bucket for similarity grouping (line 355), skipping
# facet_value(None) entries (line 368->367), and the "other" bucket plus its
# meta entry for non-similarity grouping (lines 384, 390)
# ---------------------------------------------------------------------------


def test_group_data_similarity_buckets_unmapped_nodes_as_other():
    selected = [{"name": "a", "record": {}}, {"name": "b", "record": {}}]
    node_communities = {"a": 0, "b": "other"}
    community_meta = [{"id": 0, "label": "Cluster 1", "size": 1}]

    primary, meta, values = graph_payload._group_data(selected, "similarity", node_communities, community_meta)

    assert primary["b"] == "other"
    assert {"id": "other", "label": "Other", "size": 1} in meta
    assert values["b"] == ["other"]


def test_group_data_facet_grouping_skips_wildcards_and_buckets_empties_as_other():
    selected = [
        {"name": "wildcard", "record": {"for_wikis": ["*", "commons.wikimedia.org"]}},
        {"name": "empty", "record": {}},
    ]

    primary, meta, values = graph_payload._group_data(selected, "project", {}, [])

    assert values["wildcard"] == [0]
    assert primary["empty"] == "other"
    assert {"id": "other", "label": "Other", "size": 1} in meta


# ---------------------------------------------------------------------------
# build(): malformed-row and empty-terms skip branches (lines 440, 443, 446)
# ---------------------------------------------------------------------------


def test_build_skips_malformed_rows_and_records_that_yield_no_terms(monkeypatch):
    monkeypatch.setattr(graph_payload.graph_enrichment, "merge_cached_records", lambda rows: rows)
    rows = [
        "not-a-dict",  # isinstance(row, dict) is False -> record is None -> continue (440)
        {"toolName": "no-record-key"},  # row is a dict but has no "record" -> continue (440)
        {"toolName": "", "record": {"name": "", "keywords": ["images"]}},  # empty name/toolName -> continue (443)
        {
            "toolName": "no-signal",
            "record": {"name": "no-signal", "keywords": [], "tasks": []},
        },  # no keywords/tasks -> continue (443)
        {
            "toolName": "no-entries",
            "record": {"name": "no-entries", "keywords": ["---"]},
        },  # passes the keyword check but _terms() yields nothing -> continue (446)
        {
            "toolName": "valid-tool",
            "record": {"name": "valid-tool", "title": "Valid Tool", "keywords": ["Images"]},
        },
    ]
    monkeypatch.setattr(graph_payload.canonical_tools, "records", lambda limit: rows)

    payload = graph_payload.build()

    assert [node["id"] for node in payload["nodes"]] == ["valid-tool"]
