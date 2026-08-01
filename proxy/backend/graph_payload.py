# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic graph payload built from Evolved's canonical Toolhub cache."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from typing import Any

from backend import api_cache, canonical_tools
from backend.models import utcnow
from backend.sync import SOURCE_LOCAL, SYNC_EVOLVED_REAL

GRAPH_NODE_LIMITS = (250, 500, 1000, 2000, 4000)
DEFAULT_NODE_LIMIT = GRAPH_NODE_LIMITS[0]
GRAPH_SOURCE_RECORD_LIMIT = GRAPH_NODE_LIMITS[-1]
COMMUNITY_LIMIT = 8
KNN_EDGES_PER_NODE = 4
MAX_GROUPS = 24
SPARSE_EDGE_NODE_LIMIT = 1000
SPARSE_CANDIDATE_LIMIT = 160
GRAPH_CACHE_MAX_ENTRIES = 8
GRAPH_FRESH_SECONDS = 6 * 60 * 60
GRAPH_STALE_SECONDS = 24 * 60 * 60
GRAPH_MEMORY_FRESH_SECONDS = 5 * 60
GROUP_BY_VALUES = ("similarity", "language", "project", "task", "use_case", "tool_type", "technology")
GROUP_BY_FIELDS = {
    "language": "available_ui_languages",
    "project": "for_wikis",
    "task": "tasks",
    "use_case": "audiences",
    "tool_type": "tool_type",
    "technology": "technology_used",
}
TERM_WEIGHTS = {
    "task": 1.4,
    "keyword": 1.0,
    "wiki": 0.8,
    "audience": 0.6,
    "type": 0.5,
}

_SPLIT_RE = re.compile(r"[\s_:/.-]+")
_CACHE_LOCK = Lock()
_CACHE: dict[str, Any] = {}
_REFRESH_LOCK = Lock()
_REFRESHING: set[str] = set()
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="graph-payload-cache")


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


def _sparse_knn_edges(names: list[str], vectors: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """Build deterministic nearest-neighbor edges without an all-pairs scan."""
    inverted: dict[str, set[str]] = defaultdict(set)
    for name in names:
        for term in vectors.get(name, {}):
            inverted[term].add(name)

    edge_map: dict[tuple[str, str], float] = {}
    for source in names:
        overlaps: Counter[str] = Counter()
        for term in vectors.get(source, {}):
            for target in inverted.get(term, set()):
                if target != source:
                    overlaps[target] += 1
        candidates = [name for name, _count in sorted(overlaps.items(), key=lambda item: (-item[1], item[0]))]
        scored = [
            (target, _cosine(vectors.get(source, {}), vectors.get(target, {})))
            for target in candidates[:SPARSE_CANDIDATE_LIMIT]
        ]
        scored = [(target, weight) for target, weight in scored if weight > 0]
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


def _normalize_limit(value: Any) -> int:  # noqa: ANN401 - query parameter or internal caller
    try:
        requested = int(value)
    except (TypeError, ValueError):
        return DEFAULT_NODE_LIMIT
    return min(GRAPH_NODE_LIMITS, key=lambda limit: (abs(limit - requested), limit))


def _normalize_group_by(value: Any) -> str:  # noqa: ANN401 - query parameter or internal caller
    group_by = _clean_text(value)
    return group_by if group_by in GROUP_BY_VALUES else "similarity"


def _group_label(value: str) -> str:
    return _human_label(value) if value not in {"*", "other"} else "Other"


def _group_data(
    selected: list[dict[str, Any]],
    group_by: str,
    node_communities: dict[str, int | str],
    community_meta: list[dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]], dict[str, list[str]]]:
    if group_by == "similarity":
        groups = {str(item["id"]): item for item in community_meta}
        counts = Counter(str(node_communities.get(item["name"], "other")) for item in selected)
        if counts.get("other"):
            groups["other"] = {"id": len(community_meta), "label": "Other", "size": counts["other"]}
        meta = [groups[key] for key in sorted(groups, key=lambda key: (key == "other", str(key)))]
        other_id = len(community_meta)
        primary = {
            item["name"]: int(node_communities.get(item["name"], "other"))
            if str(node_communities.get(item["name"], "other")).isdigit()
            else other_id
            for item in selected
        }
        values = {item["name"]: [str(primary[item["name"]])] for item in selected}
        return primary, meta, values

    field = GROUP_BY_FIELDS[group_by]
    counts: Counter[str] = Counter()
    values_by_name: dict[str, list[str]] = {}
    for item in selected:
        raw_values = _string_list(item["record"].get(field))
        values = sorted({value for value in raw_values if value != "*"}, key=str.casefold)
        values_by_name[item["name"]] = values
        counts.update(values)
    ordered = sorted(counts, key=lambda value: (-counts[value], value.casefold()))
    kept = ordered[: MAX_GROUPS - 1]
    group_ids = {value: index for index, value in enumerate(kept)}
    other_id = len(kept)
    group_sizes: Counter[int] = Counter()
    primary: dict[str, int] = {}
    for item in selected:
        values = values_by_name[item["name"]]
        group = next((group_ids[value] for value in values if value in group_ids), other_id)
        primary[item["name"]] = group
        group_sizes[group] += 1
    meta = [
        {"id": group, "label": _group_label(value), "size": group_sizes[group]}
        for value, group in ((value, group_ids[value]) for value in kept)
    ]
    if group_sizes[other_id]:
        meta.append({"id": other_id, "label": "Other", "size": group_sizes[other_id]})
    return primary, meta, values_by_name


def build(*, limit: int = DEFAULT_NODE_LIMIT, group_by: str = "similarity") -> dict[str, Any]:
    """Build a graph payload without making upstream Toolhub requests."""
    limit = _normalize_limit(limit)
    group_by = _normalize_group_by(group_by)
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
    selected = candidates[:limit]
    names = [item["name"] for item in selected]
    if group_by == "similarity":
        term_sets = [{f"{kind}:{term}" for kind, term, _weight in item["entries"]} for item in candidates]
        idf = _idf(term_sets)
        vectors = {item["name"]: _vector(item["entries"], idf) for item in selected}
        edges = _knn_edges(names, vectors) if limit <= SPARSE_EDGE_NODE_LIMIT else _sparse_knn_edges(names, vectors)
        labels = _detect_communities(names, edges)
        node_communities, community_meta = _communities(selected, labels)
    else:
        edges = []
        node_communities, community_meta = {}, []
    node_groups, group_meta, group_values = _group_data(selected, group_by, node_communities, community_meta)
    clustered = group_by != "similarity" or limit > SPARSE_EDGE_NODE_LIMIT
    if clustered:
        edges = []
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
            "group": node_groups.get(item["name"], 0),
            "groupValues": group_values.get(item["name"], []),
        }
        for item in selected
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": len(community_meta),
        "communityMeta": community_meta,
        "groupBy": group_by,
        "groupMeta": group_meta,
        "layout": "clustered" if clustered else "force",
        "nodeLimit": limit,
        "availableNodeLimits": list(GRAPH_NODE_LIMITS),
        "availableGroupings": list(GROUP_BY_VALUES),
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


def _cache_url(limit: int, group_by: str) -> str:
    """Return the stable synthetic URL used for the shared ToolsDB cache row."""
    return f"https://toolhub-evolved.local/v1/graph/?limit={limit}&groupBy={group_by}"


def _remember(cache_key: str, graph: dict[str, Any]) -> None:
    """Keep a short-lived per-worker L1 copy in front of the shared cache."""
    with _CACHE_LOCK:
        if cache_key not in _CACHE and len(_CACHE) >= GRAPH_CACHE_MAX_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[cache_key] = {
            "payload": graph,
            "expires_at": utcnow() + timedelta(seconds=GRAPH_MEMORY_FRESH_SECONDS),
        }


def _shared_payload(limit: int, group_by: str) -> tuple[dict[str, Any], bool] | None:
    """Read a valid fresh-or-stale graph payload from the shared ToolsDB cache."""
    cached = api_cache.get(_cache_url(limit, group_by), allow_stale=True)
    if cached is None:
        return None
    try:
        graph = json.loads(cached.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(graph, dict)
        or not isinstance(graph.get("nodes"), list)
        or not isinstance(graph.get("edges"), list)
    ):
        return None
    return graph, cached.stale


def _build_and_store(limit: int, group_by: str, cache_key: str) -> dict[str, Any]:
    """Build once, then publish the payload to both shared and worker caches."""
    graph = build(limit=limit, group_by=group_by)
    body = json.dumps(graph, sort_keys=True, separators=(",", ":")).encode("utf-8")
    api_cache.put_success(
        _cache_url(limit, group_by),
        api_cache.CacheableResponse(status=200, content_type="application/json", body=body),
        fresh_seconds=GRAPH_FRESH_SECONDS,
        stale_if_error_seconds=GRAPH_STALE_SECONDS,
    )
    _remember(cache_key, graph)
    return graph


def _refresh_worker(limit: int, group_by: str, cache_key: str) -> None:
    """Refresh a stale shared payload without putting a user back on the loader."""
    try:
        _build_and_store(limit, group_by, cache_key)
    except Exception:  # noqa: BLE001, S110 - stale graph remains usable when a background refresh fails.
        pass
    finally:
        with _REFRESH_LOCK:
            _REFRESHING.discard(cache_key)


def _queue_refresh(limit: int, group_by: str, cache_key: str) -> None:
    """Start at most one stale refresh per graph variant in this worker."""
    with _REFRESH_LOCK:
        if cache_key in _REFRESHING:
            return
        _REFRESHING.add(cache_key)
    _EXECUTOR.submit(_refresh_worker, limit, group_by, cache_key)


def payload(
    *, limit: int = DEFAULT_NODE_LIMIT, group_by: str = "similarity", force_refresh: bool = False
) -> dict[str, Any]:
    """Return an L1/shared cached graph, refreshing stale payloads asynchronously."""
    limit = _normalize_limit(limit)
    group_by = _normalize_group_by(group_by)
    cache_key = f"{limit}:{group_by}"
    now = utcnow()
    if not force_refresh:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached is not None and now < cached["expires_at"]:
                return cached["payload"]
        shared = _shared_payload(limit, group_by)
        if shared is not None:
            graph, stale = shared
            _remember(cache_key, graph)
            if stale:
                _queue_refresh(limit, group_by, cache_key)
            return graph
    return _build_and_store(limit, group_by, cache_key)
