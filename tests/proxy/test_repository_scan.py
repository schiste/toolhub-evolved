# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic repository acquisition and incremental scanning."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import repository_scan  # noqa: E402
from backend import db  # noqa: E402
from backend.models import RepositoryAnalysisState, SourceAnalysisReport  # noqa: E402


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
