"""Integration tests for provenance-aware graph facet materialization."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

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


def test_refresh_tool_names_batches_without_dropping_large_feeds(monkeypatch):
    batches = []

    def fake_refresh(names):
        batches.append(names)
        return {"requested": len(names), "refreshed": len(names), "changed": len(names), "errors": 0}

    monkeypatch.setattr(graph_enrichment, "_refresh_batch", fake_refresh)
    names = [f"tool-{index}" for index in range(graph_enrichment.MAX_REFRESH_TOOLS + 1)]

    summary = graph_enrichment.refresh_tool_names([*names, names[0], " "])

    assert [len(batch) for batch in batches] == [graph_enrichment.MAX_REFRESH_TOOLS, 1]
    assert summary == {
        "requested": graph_enrichment.MAX_REFRESH_TOOLS + 1,
        "refreshed": graph_enrichment.MAX_REFRESH_TOOLS + 1,
        "changed": graph_enrichment.MAX_REFRESH_TOOLS + 1,
        "errors": 0,
    }


def test_source_rows_skips_non_dict_payloads():
    now = utcnow()
    with db.session_scope() as s:
        source = ToolinfoSource(url="https://official.example/toolinfo.json", valid=True, last_fetched_at=now)
        s.add(source)
        s.flush()
        s.add(
            ToolinfoSourceItem(
                tool_name="malformed",
                source_id=source.id,
                source_url=source.url,
                payload=None,
                last_seen_at=now,
            )
        )

    with db.session_scope() as s:
        rows = graph_enrichment._source_rows(s, ["malformed"])

    assert rows == {}


def test_latest_reports_skips_rows_with_a_blank_tool_name():
    with db.session_scope() as s:
        user = User(wm_sub="blank-scanner", username="Blank")
        s.add(user)
        s.flush()
        s.add(
            SourceAnalysisReport(
                user_id=user.id,
                tool_name="",
                review_status=REVIEW_APPROVED,
                report={},
            )
        )

    with db.session_scope() as s:
        reports = graph_enrichment._latest_reports(s, [""])

    assert reports == {}


def test_merge_sources_tolerates_missing_timestamps_and_duplicate_evidence():
    sources = [
        ({"for_wikis": ["a", "a"], "tool_type": "bot"}, "src1", None),
        ({"tool_type": "bot"}, "src1", None),
    ]

    facets, provenance, timestamps, derived_seen = graph_enrichment._merge_sources(sources)

    assert facets == {"for_wikis": ["a"], "tool_type": "bot"}
    assert timestamps == {}
    assert derived_seen is True
    assert provenance["for_wikis"] == [{"value": "a", "sources": [{"source": "src1"}]}]
    assert provenance["tool_type"] == [{"value": "bot", "sources": [{"source": "src1"}]}]


def test_mark_failures_writes_error_state_and_backs_off():
    with db.session_scope() as s:
        s.add(GraphToolEnrichment(tool_name="flaky", status=graph_enrichment.STATUS_ENRICHED))

    graph_enrichment._mark_failures(["flaky", "new-name"], ValueError("  boom   happened  "))

    with db.session_scope() as s:
        flaky = s.get(GraphToolEnrichment, "flaky")
        assert flaky.status == graph_enrichment.STATUS_ERROR
        assert flaky.attempts == 1
        assert flaky.last_error == "boom happened"
        assert flaky.next_attempt_at is not None
        created = s.get(GraphToolEnrichment, "new-name")
        assert created is not None
        assert created.status == graph_enrichment.STATUS_ERROR
        assert created.attempts == 1


def test_mark_failures_swallows_a_nested_database_error(monkeypatch):
    class _BoomScope:
        def __enter__(self):
            raise SQLAlchemyError("double fault")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(graph_enrichment.db, "session_scope", lambda: _BoomScope())

    graph_enrichment._mark_failures(["ignored"], ValueError("original"))


def test_refresh_batch_with_no_names_returns_zero_summary():
    assert graph_enrichment._refresh_batch([]) == {"requested": 0, "refreshed": 0, "changed": 0, "errors": 0}


def test_refresh_reuses_an_existing_enrichment_row_instead_of_recreating_it():
    with db.session_scope() as s:
        s.add(_canonical("existing"))
        s.add(GraphToolEnrichment(tool_name="existing", status="pending"))

    summary = graph_enrichment.refresh_tool_names(["existing"])

    assert summary["refreshed"] == 1
    with db.session_scope() as s:
        assert s.query(GraphToolEnrichment).filter_by(tool_name="existing").count() == 1
        assert s.get(GraphToolEnrichment, "existing").status == graph_enrichment.STATUS_NO_METADATA


def test_refresh_is_idempotent_and_skips_cache_invalidation_when_unchanged(monkeypatch):
    with db.session_scope() as s:
        s.add(_canonical("stable", for_wikis=["wikidatawiki"]))
    graph_enrichment.refresh_tool_names(["stable"])

    invalidations = []
    monkeypatch.setattr(graph_enrichment.api_cache, "invalidate_graph", lambda: invalidations.append(True))

    summary = graph_enrichment.refresh_tool_names(["stable"])

    assert summary["changed"] == 0
    assert invalidations == []


def test_refresh_batch_records_failures_when_merge_raises(monkeypatch):
    with db.session_scope() as s:
        s.add(_canonical("broken"))
    monkeypatch.setattr(
        graph_enrichment,
        "_merge_sources",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("merge exploded")),
    )

    summary = graph_enrichment.refresh_tool_names(["broken"])

    assert summary == {"requested": 1, "refreshed": 0, "changed": 0, "errors": 1}
    with db.session_scope() as s:
        row = s.get(GraphToolEnrichment, "broken")
        assert row.status == graph_enrichment.STATUS_ERROR
        assert row.attempts == 1


def test_refresh_candidates_skips_scheduled_retries_and_up_to_date_rows():
    with db.session_scope() as s:
        s.add(_canonical("scheduled"))
        s.add(
            GraphToolEnrichment(
                tool_name="scheduled",
                enrichment_version=graph_enrichment.ENRICHMENT_VERSION,
                status="pending",
                next_attempt_at=utcnow() + timedelta(hours=1),
            )
        )
        s.add(_canonical("current"))
        s.add(
            GraphToolEnrichment(
                tool_name="current",
                enrichment_version=graph_enrichment.ENRICHMENT_VERSION,
                status=graph_enrichment.STATUS_ENRICHED,
            )
        )

    summary = graph_enrichment.refresh_candidates(limit=10)

    assert summary["candidates"] == 0
    assert summary["requested"] == 0


def test_merge_cached_records_backfills_a_missing_scalar_facet():
    with db.session_scope() as s:
        s.add(
            GraphToolEnrichment(
                tool_name="scalar-fill",
                enrichment_version=graph_enrichment.ENRICHMENT_VERSION,
                status=graph_enrichment.STATUS_ENRICHED,
                facets={"tool_type": "bot"},
            )
        )

    rows = [{"toolName": "scalar-fill", "record": {"name": "scalar-fill"}}]
    out = graph_enrichment.merge_cached_records(rows)

    assert out[0]["record"]["tool_type"] == "bot"


def test_status_summary_counts_by_status_and_flags_stale_versions():
    with db.session_scope() as s:
        s.add(_canonical("c1"))
        s.add(_canonical("c2"))
        s.add(
            GraphToolEnrichment(
                tool_name="c1",
                enrichment_version=graph_enrichment.ENRICHMENT_VERSION,
                status=graph_enrichment.STATUS_ENRICHED,
            )
        )
        s.add(
            GraphToolEnrichment(
                tool_name="c2",
                enrichment_version=graph_enrichment.ENRICHMENT_VERSION - 1,
                status=graph_enrichment.STATUS_NO_METADATA,
            )
        )

    summary = graph_enrichment.status_summary()

    assert summary["canonical"] == 2
    assert summary["materialized"] == 2
    assert summary[graph_enrichment.STATUS_ENRICHED] == 1
    assert summary[graph_enrichment.STATUS_NO_METADATA] == 1
    assert summary["stale_version"] == 1
