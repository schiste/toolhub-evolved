# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic repository acquisition and incremental scanning."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import repository_scan  # noqa: E402
from backend import db  # noqa: E402
from backend.models import CanonicalToolCache, RepositoryAnalysisState, SourceAnalysisReport  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def test_repository_url_accepts_supported_https_hosts_and_strips_query():
    assert (
        repository_scan.repository_url("https://github.com/example/tool.git?tab=readme")
        == "https://github.com/example/tool.git"
    )
    assert repository_scan.provider_for("https://gitlab.wikimedia.org/example/tool") == "gitlab-wikimedia"
    assert repository_scan.provider_for("https://codeberg.org/example/tool") == "codeberg"


def test_repository_url_rejects_credentials_private_hosts_and_non_https():
    assert repository_scan.repository_url("http://github.com/example/tool") == ""
    assert repository_scan.repository_url("https://user:secret@github.com/example/tool") == ""
    assert repository_scan.repository_url("https://example.org/example/tool") == ""
    assert repository_scan.repository_url("https://github.com/example/../private") == ""


def test_repository_head_parses_only_head_sha(monkeypatch):
    monkeypatch.setattr(
        repository_scan,
        "_git",
        lambda args, cwd=None: "ref: refs/heads/main\tHEAD\nabc1234567890123456789012345678901234567\tHEAD",
    )

    assert (
        repository_scan.repository_head("https://github.com/example/tool") == "abc1234567890123456789012345678901234567"
    )


def test_scan_tool_skips_same_commit_without_cloning(monkeypatch):
    # State is enough to exercise the incremental branch without requiring a live clone.
    with db.session_scope() as s:
        s.add(
            RepositoryAnalysisState(
                tool_name="example-tool",
                repository_url="https://github.com/example/tool",
                commit_sha="abc1234567890123456789012345678901234567",
                status="analyzed",
                report_id=1,
            )
        )
    monkeypatch.setattr(repository_scan, "repository_head", lambda _url: "abc1234567890123456789012345678901234567")
    monkeypatch.setattr(repository_scan, "checkout_repository", lambda *_args: pytest.fail("clone should be skipped"))

    assert repository_scan.scan_tool("example-tool", {"repository": "https://github.com/example/tool"}) == "skipped"


def test_checkout_size_ignores_symlink_targets(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_bytes(b"secret")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    assert repository_scan._checkout_size(tmp_path) == len(b"secret")


def test_scan_tool_stores_approved_repository_report_and_commit_state(monkeypatch):
    commit = "abc1234567890123456789012345678901234567"
    monkeypatch.setattr(repository_scan, "repository_head", lambda _url: commit)

    def fake_checkout(_url, destination):
        destination.mkdir(parents=True)
        return commit

    monkeypatch.setattr(repository_scan, "checkout_repository", fake_checkout)
    monkeypatch.setattr(repository_scan, "_read_tree", lambda _paths: [{"path": "README.md", "content": "tool"}])
    monkeypatch.setattr(
        repository_scan,
        "_local_git_context",
        lambda _paths: {"repository": {"branch": "main", "commitSha": commit}},
    )
    monkeypatch.setattr(
        repository_scan,
        "analyze_source_files",
        lambda files, **kwargs: {
            "filesAnalyzed": len(files),
            "healthCore": {"score": 80, "grade": "good"},
            "repositoryContext": kwargs["repository_context"],
        },
    )
    monkeypatch.setattr(repository_scan.tool_summaries, "refresh", lambda *_args: 1)

    result = repository_scan.scan_tool("example-tool", {"repository": "https://github.com/example/tool"})

    assert result == "analyzed"
    with db.session_scope() as s:
        report = s.execute(
            select(SourceAnalysisReport).where(SourceAnalysisReport.tool_name == "example-tool")
        ).scalar_one()
        state = s.get(RepositoryAnalysisState, "example-tool")
        assert report.review_status == "approved"
        assert report.source == "repository_scan"
        assert report.report["repositoryContext"]["repository"]["commitSha"] == commit
        assert state is not None
        assert state.status == "analyzed"
        assert state.commit_sha == commit
        assert state.report_id == report.id


def test_run_records_unexpected_tool_failure_and_continues(monkeypatch):
    candidates = [("bad-tool", {"repository": "https://github.com/example/bad"}), ("good-tool", {})]
    failures = []
    monkeypatch.setattr(repository_scan, "candidate_tools", lambda *_args, **_kwargs: candidates)

    def fake_scan(name, _record, *, force=False):
        if name == "bad-tool":
            raise RuntimeError("unexpected scanner failure")
        return "skipped"

    monkeypatch.setattr(repository_scan, "scan_tool", fake_scan)
    monkeypatch.setattr(repository_scan, "_save_failure", lambda name, url, provider, error: failures.append(name))

    assert repository_scan.run(limit=2) == {
        "candidates": 2,
        "analyzed": 0,
        "skipped": 1,
        "backoff": 0,
        "unsupported": 0,
        "error": 1,
    }
    assert failures == ["bad-tool"]


def test_scan_tool_produces_analyzer_facets_end_to_end(monkeypatch):
    """Pin the one path that delivers analyzer facets between deploys.

    scan_tool -> graph_enrichment.refresh_tool_names (repository_scan.py:309)
    -> catalog_projection. This link is easy to sever by accident and the
    projection's own tests start downstream of it, so drive the real
    scan_tool with only the network/filesystem boundary stubbed.
    """
    from datetime import timedelta

    from backend.models import CanonicalToolCache, CatalogFacetValue, utcnow

    record = {
        "name": "omega",
        "title": "Omega",
        "description": "scans things",
        "repository": "https://github.com/example/omega",
        "technology_used": ["Python"],
    }
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="omega",
                record=record,
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )

    monkeypatch.setattr(repository_scan, "repository_head", lambda url: "abc123")
    monkeypatch.setattr(repository_scan, "checkout_repository", lambda url, dest: "abc123")
    monkeypatch.setattr(repository_scan, "_read_tree", lambda paths: [])
    monkeypatch.setattr(repository_scan, "_local_git_context", lambda paths: {})
    monkeypatch.setattr(
        repository_scan,
        "analyze_source_files",
        lambda files, **kwargs: {
            "dependencies": [{"value": "pypi:pywikibot", "label": "pywikibot (pypi)", "confidence": 0.95}],
            "apis": [{"value": "wikidata-query-service", "label": "WDQS", "confidence": 0.94}],
            "technology": [{"value": "Python", "label": "Python", "confidence": 0.64}],
        },
    )

    assert repository_scan.scan_tool("omega", record) == "analyzed"

    with db.session_scope() as s:
        facets = {
            (row.field, row.value)
            for row in s.execute(select(CatalogFacetValue).where(CatalogFacetValue.tool_name == "omega")).scalars()
        }
    assert ("dependency", "pypi:pywikibot") in facets
    assert ("wikimedia_api", "wikidata-query-service") in facets
    assert ("detected_technology", "python") in facets
    # The declared pass still ran in the same projection.
    assert ("technology", "python") in facets

def _cached_tool(session, name):
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    session.add(
        CanonicalToolCache(
            tool_name=name,
            record={"name": name, "repository": f"https://github.com/example/{name}"},
            source_url=f"https://toolhub.example/{name}",
            expires_at=now + timedelta(days=1),
            stale_until=now + timedelta(days=2),
        )
    )


def test_a_pending_state_row_with_no_checked_at_does_not_break_ordering():
    """scan_tool() commits a pending row before scanning, so a run killed
    between the two leaves checked_at NULL. Sorting that against a datetime
    raised TypeError on every later run, which is how one job timeout took
    repository-analysis down for twelve days."""
    with db.session_scope() as s:
        _cached_tool(s, "killed-midscan")
        _cached_tool(s, "never-seen")
        _cached_tool(s, "checked-recently")
        s.add(RepositoryAnalysisState(tool_name="killed-midscan", status="pending", checked_at=None))
        s.add(
            RepositoryAnalysisState(
                tool_name="checked-recently",
                status="analyzed",
                checked_at=datetime.now(tz=UTC).replace(tzinfo=None),
            )
        )

    names = [name for name, _record in repository_scan.candidate_tools(10)]

    # No state row at all still comes first, then the never-checked row, then
    # the recently checked one.
    assert names == ["never-seen", "killed-midscan", "checked-recently"]


def test_the_limit_still_applies_when_a_null_checked_at_is_present():
    with db.session_scope() as s:
        for index in range(4):
            _cached_tool(s, f"tool-{index}")
        s.add(RepositoryAnalysisState(tool_name="tool-0", status="pending", checked_at=None))

    assert len(repository_scan.candidate_tools(2)) == 2
