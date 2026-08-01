"""Integration tests for provenance-aware graph facet materialization."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, graph_enrichment, graph_payload  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    GraphToolEnrichment,
    SourceAnalysisReport,
    ToolinfoDiscovery,
    ToolinfoSource,
    ToolinfoSourceItem,
    User,
    utcnow,
)
from backend.sync import REVIEW_APPROVED  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()
    graph_payload._CACHE.clear()


def _canonical(name: str, **fields):
    now = utcnow()
    return CanonicalToolCache(
        tool_name=name,
        record={"name": name, "title": name, "keywords": ["graph"], **fields},
        source_url=f"https://toolhub.wikimedia.org/api/tools/{name}/",
        fetched_at=now,
        expires_at=now,
        stale_until=now,
    )


def test_refresh_merges_sources_in_precedence_order_with_provenance(monkeypatch):
    now = utcnow()
    with db.session_scope() as s:
        s.add(_canonical("mixed", for_wikis=["wikidatawiki"], technology_used=["Toolforge"], tool_type="web app"))
        source = ToolinfoSource(
            url="https://official.example/toolinfo.json",
            valid=True,
            last_fetched_at=now,
        )
        s.add(source)
        s.flush()
        s.add(
            ToolinfoSourceItem(
                tool_name="mixed",
                source_id=source.id,
                source_url=source.url,
                payload={"for_wikis": ["commonswiki"], "technology_used": ["Python"], "tool_type": "bot"},
                last_seen_at=now,
            )
        )
        s.add(
            ToolinfoDiscovery(
                tool_name="mixed",
                tool_url="https://mixed.example",
                status="found",
                payload={"technology_used": ["React"], "for_wikis": ["wikidatawiki"]},
                checked_at=now,
            )
        )
        user = User(wm_sub="scanner", username="Scanner")
        s.add(user)
        s.flush()
        s.add(
            SourceAnalysisReport(
                user_id=user.id,
                tool_name="mixed",
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
                report={"suggestions": {"toolinfoPatch": {"for_wikis": ["enwiki"], "technology_used": ["Deno"]}}},
            )
        )
    invalidations = []
    monkeypatch.setattr(graph_enrichment.api_cache, "invalidate_graph", lambda: invalidations.append(True) or 1)

    summary = graph_enrichment.refresh_tool_names(["mixed"])

    assert summary == {"requested": 1, "refreshed": 1, "changed": 1, "errors": 0}
    assert invalidations == [True]
    with db.session_scope() as s:
        row = s.get(GraphToolEnrichment, "mixed")
        assert row.status == graph_enrichment.STATUS_ENRICHED
        assert row.facets == {
            "for_wikis": ["wikidatawiki", "commonswiki", "enwiki"],
            "technology_used": ["Toolforge", "Python", "React", "Deno"],
            "tool_type": "web app",
        }
        project = {item["value"]: item["sources"] for item in row.provenance["for_wikis"]}
        assert {source["source"] for source in project["wikidatawiki"]} == {
            graph_enrichment.SOURCE_CANONICAL,
            graph_enrichment.SOURCE_DISCOVERY,
        }
        assert project["commonswiki"][0]["source"] == graph_enrichment.SOURCE_CRAWLER
        assert project["enwiki"][0]["source"] == graph_enrichment.SOURCE_REPOSITORY


def test_graph_build_consumes_materialized_facets_without_mutating_canonical():
    with db.session_scope() as s:
        s.add_all([_canonical("one"), _canonical("two")])
        s.add(
            GraphToolEnrichment(
                tool_name="one",
                enrichment_version=graph_enrichment.ENRICHMENT_VERSION,
                status="enriched",
                facets={"for_wikis": ["wikidatawiki"]},
            )
        )
        s.add(
            GraphToolEnrichment(
                tool_name="two",
                enrichment_version=graph_enrichment.ENRICHMENT_VERSION,
                status="enriched",
                facets={"for_wikis": ["commonswiki"]},
            )
        )

    payload = graph_payload.build(group_by="project")

    assert [group["label"] for group in payload["groupMeta"]] == ["Wikidata", "Wikimedia Commons"]
    assert {node["id"]: node["projects"] for node in payload["nodes"]} == {
        "one": ["wikidatawiki"],
        "two": ["commonswiki"],
    }
    with db.session_scope() as s:
        assert s.get(CanonicalToolCache, "one").record.get("for_wikis") is None


def test_repair_prioritizes_graph_eligible_missing_metadata():
    with db.session_scope() as s:
        s.add(_canonical("eligible"))
        s.add(
            CanonicalToolCache(
                tool_name="not-eligible",
                record={"name": "not-eligible", "title": "Not eligible"},
                source_url="https://toolhub.wikimedia.org/api/tools/not-eligible/",
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )

    summary = graph_enrichment.refresh_candidates(limit=1)

    assert summary["candidates"] == 2
    with db.session_scope() as s:
        assert s.get(GraphToolEnrichment, "eligible") is not None
        assert s.get(GraphToolEnrichment, "not-eligible") is None
