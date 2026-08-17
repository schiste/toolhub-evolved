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
    monkeypatch.setattr(repository_scan, "clone_repository", lambda *_args: pytest.fail("clone should be skipped"))

    assert repository_scan.scan_tool("example-tool", {"repository": "https://github.com/example/tool"}) == "skipped"


def test_repository_size_ignores_symlink_targets(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_bytes(b"secret")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    assert repository_scan._repository_size(tmp_path) == len(b"secret")


def test_scan_tool_stores_approved_repository_report_and_commit_state(monkeypatch):
    commit = "abc1234567890123456789012345678901234567"
    monkeypatch.setattr(repository_scan, "repository_head", lambda _url: commit)

    def fake_checkout(_url, destination):
        destination.mkdir(parents=True)
        return commit

    monkeypatch.setattr(repository_scan, "clone_repository", fake_checkout)
    monkeypatch.setattr(repository_scan, "_read_repository_tree", lambda _repo: [{"path": "README.md", "content": "tool"}])
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
    monkeypatch.setattr(repository_scan, "clone_repository", lambda url, dest: "abc123")
    monkeypatch.setattr(repository_scan, "_read_repository_tree", lambda repo: [])
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


def _seed_origin(root: Path) -> Path:
    """Build a repository whose analyzable content is a tiny fraction of its bytes."""
    origin = root / "origin"
    origin.mkdir()
    repository_scan._git(["init", "-q", "--initial-branch=main", "."], cwd=origin)
    # A file:// remote only honours --filter when it advertises the capability.
    repository_scan._git(["config", "uploadpack.allowFilter", "true"], cwd=origin)
    (origin / "pkg").mkdir()
    (origin / "pkg" / "small.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    (origin / "pkg" / "oversized.py").write_text("x" * (repository_scan.MAX_FILE_BYTES + 1), encoding="utf-8")
    (origin / "pkg" / "payload.bin").write_bytes(b"\x00\xff" * 3_000_000)
    (origin / "vendored.py").symlink_to(origin / "pkg" / "small.py")
    (origin / "node_modules").mkdir()
    (origin / "node_modules" / "dep.py").write_text("import os\n", encoding="utf-8")
    repository_scan._git(["add", "-A"], cwd=origin)
    repository_scan._git(
        ["-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init"], cwd=origin
    )
    return origin


def test_clone_fetches_only_analyzable_blobs(tmp_path):
    origin = _seed_origin(tmp_path)
    checkout = tmp_path / "checkout"

    head = repository_scan.clone_repository(f"file://{origin}", checkout)
    fetched = repository_scan._repository_size(checkout)
    files = repository_scan._read_repository_tree(checkout)

    assert repository_scan.SHA_RE.fullmatch(head)
    # Only the one small source survives: the oversized source and the binary
    # are filtered out of the pack, the symlink and node_modules are excluded
    # by mode and by ignored-directory name.
    assert [entry["path"] for entry in files] == ["pkg/small.py"]
    assert files[0]["content"] == "def hello():\n    return 1\n"
    # The clone must stay far below the 6MB payload it never asked for. A
    # regression that reintroduces the unbounded fetch blows straight past this.
    assert fetched < 1_000_000


def test_clone_leaves_filtered_blobs_unfetched(tmp_path):
    origin = _seed_origin(tmp_path)
    checkout = tmp_path / "checkout"
    repository_scan.clone_repository(f"file://{origin}", checkout)

    entries = dict(repository_scan._tree_entries(checkout))
    oids = list(entries.keys())
    blobs = repository_scan._read_blobs(checkout, oids)

    # Every tree entry is listed without reading a blob, but only the small one
    # is actually present locally; the rest answer "missing" and stay missing.
    by_path = {path: oid for oid, path in repository_scan._tree_entries(checkout)}
    assert set(by_path) == {"pkg/small.py", "pkg/oversized.py", "pkg/payload.bin", "node_modules/dep.py"}
    assert blobs[by_path["pkg/small.py"]] == b"def hello():\n    return 1\n"
    assert by_path["pkg/payload.bin"] not in blobs
    assert by_path["pkg/oversized.py"] not in blobs


def test_read_tree_tops_up_past_rejected_candidates(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    repository_scan._git(["init", "-q", "--initial-branch=main", "."], cwd=origin)
    repository_scan._git(["config", "uploadpack.allowFilter", "true"], cwd=origin)
    oversized = "x" * (repository_scan.MAX_FILE_BYTES + 1)
    # The first ten candidates in path order are all unreadable, so a reader that
    # selected exactly MAX_FILES candidates up front would come back ten short.
    for index in range(140):
        body = oversized if index < 10 else f"value = {index}\n"
        (origin / f"mod{index:03d}.py").write_text(body, encoding="utf-8")
    repository_scan._git(["add", "-A"], cwd=origin)
    repository_scan._git(
        ["-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init"], cwd=origin
    )

    checkout = tmp_path / "checkout"
    repository_scan.clone_repository(f"file://{origin}", checkout)
    files = repository_scan._read_repository_tree(checkout)

    assert len(files) == repository_scan.MAX_FILES
    assert [entry["path"] for entry in files] == [f"mod{index:03d}.py" for index in range(10, 130)]


def test_parse_batch_skips_bodiless_replies_without_desynchronising():
    stream = (
        b"aa missing\n"  # filtered out for exceeding MAX_FILE_BYTES
        b"bb ambiguous\n"  # the other two-field reply, which must not be indexed as a size
        b"cc blob 5\nhello\n"
        b"dd missing\n"
        b"ee blob 2\nhi\n"
    )

    assert repository_scan._parse_batch(stream) == {"cc": b"hello", "ee": b"hi"}


def test_parse_batch_consumes_unexpected_object_bodies():
    stream = b"aa tree 4\nbody\nbb blob 3\nend\n"

    # The tree body is stepped over rather than parsed as the next header, so
    # the blob that follows it is still recovered.
    assert repository_scan._parse_batch(stream) == {"bb": b"end"}
