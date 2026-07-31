# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic graph payload built from Evolved's canonical Toolhub cache."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import timedelta
from threading import Lock
from typing import Any

from backend import canonical_tools
from backend.models import utcnow
from backend.sync import SOURCE_LOCAL, SYNC_EVOLVED_REAL

GLOBAL_NODE_LIMIT = 250
GRAPH_SOURCE_RECORD_LIMIT = 1000
COMMUNITY_LIMIT = 8
KNN_EDGES_PER_NODE = 4
GRAPH_FRESH_SECONDS = 6 * 60 * 60
TERM_WEIGHTS = {
    "task": 1.4,
    "keyword": 1.0,
    "wiki": 0.8,
    "audience": 0.6,
    "type": 0.5,
}

_SPLIT_RE = re.compile(r"[\s_:/.-]+")
_CACHE_LOCK = Lock()
_CACHE: dict[str, Any] = {"payload": None, "expires_at": utcnow()}


def _clean_text(value: Any) -> str:  # noqa: ANN401 - official API JSON
    return str(value or "").strip()


def _localized_text(value: Any) -> str:  # noqa: ANN401 - official API JSON
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("en", "mul"):
            text = _clean_text(value.get(key))
            if text:
                return text
        for text in value.values():
            clean = _clean_text(text)
            if clean:
                return clean
    return ""


def _string_list(value: Any) -> list[str]:  # noqa: ANN401 - official API JSON
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    text = _clean_text(value)
    return [text] if text else []


def _term(value: str) -> str:
    return " ".join(part for part in _SPLIT_RE.split(value.casefold()) if part)


def _human_label(value: str) -> str:
    return " ".join(part for part in _SPLIT_RE.split(value) if part).strip() or value


def _terms(record: dict[str, Any]) -> list[tuple[str, str, float]]:
    out: list[tuple[str, str, float]] = []
    for key, kind in (("tasks", "task"), ("keywords", "keyword"), ("audiences", "audience")):
        for raw in _string_list(record.get(key)):
            term = _term(raw)
            if term:
                out.append((kind, term, TERM_WEIGHTS[kind]))
    for raw in _string_list(record.get("for_wikis")):
        if raw == "*":
            continue
        term = _term(raw)
        if term:
            out.append(("wiki", term, TERM_WEIGHTS["wiki"]))
    tool_type = _term(_clean_text(record.get("tool_type")))
    if tool_type:
        out.append(("type", tool_type, TERM_WEIGHTS["type"]))
    return out


def _richness(record: dict[str, Any]) -> int:
    return sum(
        len(_string_list(record.get(key))) for key in ("keywords", "tasks", "audiences", "for_wikis", "technology_used")
    )


def _idf(term_sets: list[set[str]]) -> dict[str, float]:
    total = max(1, len(term_sets))
    counts = Counter(term for terms in term_sets for term in terms)
    return {term: math.log((1 + total) / (1 + count)) + 1 for term, count in counts.items()}


def _vector(entries: list[tuple[str, str, float]], idf: dict[str, float]) -> dict[str, float]:
    vector: dict[str, float] = {}
    for kind, term, weight in entries:
        key = f"{kind}:{term}"
        vector[key] = vector.get(key, 0.0) + weight * idf.get(key, 1.0)
    return vector


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    smaller, larger = (a, b) if len(a) < len(b) else (b, a)
    dot = sum(value * larger.get(key, 0.0) for key, value in smaller.items())
    if dot <= 0:
        return 0.0
    a_norm = math.sqrt(sum(value * value for value in a.values()))
    b_norm = math.sqrt(sum(value * value for value in b.values()))
    return dot / (a_norm * b_norm) if a_norm and b_norm else 0.0


def _sorted_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _knn_edges(names: list[str], vectors: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    edge_map: dict[tuple[str, str], float] = {}
    for source in names:
        scored: list[tuple[str, float]] = []
        for target in names:
            if target == source:
                continue
            weight = _cosine(vectors.get(source, {}), vectors.get(target, {}))
            if weight > 0:
                scored.append((target, weight))
        scored.sort(key=lambda item: (-item[1], item[0]))
        for target, weight in scored[:KNN_EDGES_PER_NODE]:
            key = _sorted_pair(source, target)
            edge_map[key] = max(edge_map.get(key, 0.0), weight)
    return [
        {"source": source, "target": target, "weight": round(weight, 4)}
        for (source, target), weight in sorted(edge_map.items())
    ]


def _detect_communities(names: list[str], edges: list[dict[str, Any]]) -> dict[str, str]:
    labels = {name: name for name in sorted(names)}
    adjacency: dict[str, list[tuple[str, float]]] = {name: [] for name in labels}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in adjacency or target not in adjacency:
            continue
        weight = float(edge.get("weight") or 0)
        adjacency[source].append((target, weight))
        adjacency[target].append((source, weight))
    for _pass in range(8):
        changed = False
        for name in sorted(labels):
            scores: dict[str, float] = defaultdict(float)
            for neighbor, weight in adjacency[name]:
                scores[labels[neighbor]] += weight
            best_label = labels[name]
            best_score = -1.0
            for label, score in scores.items():
                if score > best_score or (score == best_score and label < best_label):
                    best_label = label
                    best_score = score
            if best_score >= 0 and best_label != labels[name]:
                labels[name] = best_label
                changed = True
        if not changed:
            break
    return labels


def _ranked_terms(items: list[dict[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    for item in items:
        record = item["record"]
        for key in ("keywords", "tasks", "audiences"):
            for raw in _string_list(record.get(key)):
                label = _human_label(raw)
                if label:
                    counts[label] += 1
    return [label for label, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))]


def _communities(
    selected: list[dict[str, Any]], labels: dict[str, str]
) -> tuple[dict[str, int | str], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        grouped[labels.get(item["name"], item["name"])].append(item)
    ordered = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    kept = ordered[:COMMUNITY_LIMIT]
    remap = {label: index for index, (label, _items) in enumerate(kept)}
    node_communities = {item["name"]: remap.get(labels.get(item["name"], item["name"]), "other") for item in selected}
    used_terms: set[str] = set()
    meta = []
    for index, (_label, items) in enumerate(kept):
        label = next((term for term in _ranked_terms(items) if term.casefold() not in used_terms), None)
        if label:
            used_terms.add(label.casefold())
        else:
            label = f"Cluster {index + 1}"
        meta.append({"id": index, "label": label, "size": len(items)})
    return node_communities, meta


def build() -> dict[str, Any]:
    """Build a graph payload without making upstream Toolhub requests."""
    rows = canonical_tools.records(limit=GRAPH_SOURCE_RECORD_LIMIT)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        record = row.get("record") if isinstance(row, dict) else None
        if not isinstance(record, dict):
            continue
        name = _clean_text(record.get("name") or row.get("toolName"))
        if not name or not (_string_list(record.get("keywords")) or _string_list(record.get("tasks"))):
            continue
        entries = _terms(record)
        if not entries:
            continue
        candidates.append(
            {
                "name": name,
                "title": _localized_text(record.get("title")) or name,
                "record": record,
                "entries": entries,
                "richness": _richness(record),
            }
        )

    candidates.sort(key=lambda item: (-item["richness"], item["title"].casefold(), item["name"]))
    selected = candidates[:GLOBAL_NODE_LIMIT]
    term_sets = [{f"{kind}:{term}" for kind, term, _weight in item["entries"]} for item in candidates]
    idf = _idf(term_sets)
    vectors = {item["name"]: _vector(item["entries"], idf) for item in selected}
    names = [item["name"] for item in selected]
    edges = _knn_edges(names, vectors)
    labels = _detect_communities(names, edges)
    node_communities, community_meta = _communities(selected, labels)
    degree = Counter()
    for edge in edges:
        degree[str(edge["source"])] += 1
        degree[str(edge["target"])] += 1
    nodes = [
        {
            "id": item["name"],
            "title": item["title"],
            "community": node_communities.get(item["name"], 0),
            "weight": degree[item["name"]],
            "endorsement": 0,
            "fits": False,
            "projects": _string_list(item["record"].get("for_wikis")),
            "languages": _string_list(item["record"].get("available_ui_languages")),
        }
        for item in selected
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": len(community_meta),
        "communityMeta": community_meta,
        "truncated": max(0, len(candidates) - len(selected)),
        "generatedAt": utcnow().isoformat(timespec="seconds") + "Z",
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
        "cachePolicy": {
            "canonical": True,
            "upstream": False,
            "summary": "Derived from Evolved's structured canonical Toolhub cache; no browser-side upstream crawl.",
        },
    }


def payload(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return the cached graph payload, rebuilding from local data when stale."""
    now = utcnow()
    with _CACHE_LOCK:
        cached = _CACHE.get("payload")
        if not force_refresh and cached is not None and now < _CACHE["expires_at"]:
            return cached
    fresh = build()
    with _CACHE_LOCK:
        _CACHE["payload"] = fresh
        _CACHE["expires_at"] = utcnow() + timedelta(seconds=GRAPH_FRESH_SECONDS)
    return fresh
