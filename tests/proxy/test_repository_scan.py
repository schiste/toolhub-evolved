# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic repository acquisition and incremental scanning."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import repository_scan  # noqa: E402
from backend import db  # noqa: E402
from backend import job_catalog  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    JobRun,
    RepositoryAnalysisState,
    SourceAnalysisReport,
)


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
    monkeypatch.setattr(
        repository_scan, "_read_repository_tree", lambda _repo: [{"path": "README.md", "content": "tool"}]
    )
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


def test_what_the_checkout_measured_survives_into_the_stored_report(monkeypatch):
    # _report_context used to look for a "repositoryContext" key on the context
    # it was handed, which a context does not have, so every measured fact was
    # silently dropped: no lastCommitAt reached the analyzer and the dormancy
    # assessment had nothing to score.
    commit = "abc1234567890123456789012345678901234567"
    monkeypatch.setattr(repository_scan, "repository_head", lambda _url: commit)

    def fake_checkout(_url, destination):
        destination.mkdir(parents=True)
        return commit

    monkeypatch.setattr(repository_scan, "clone_repository", fake_checkout)
    monkeypatch.setattr(repository_scan, "_read_repository_tree", lambda _repo: [{"path": "a.py", "content": "x = 1"}])
    monkeypatch.setattr(
        repository_scan,
        "_local_git_context",
        lambda _paths: {
            "repository": {
                "branch": "main",
                "lastCommitAt": "2025-02-03T04:05:06Z",
                # Both read off a --depth 1 checkout, so both are our own
                # artefact rather than a fact about the repository.
                "commitCount": 1,
                "contributorCount": 1,
            }
        },
    )
    monkeypatch.setattr(
        repository_scan,
        "analyze_source_files",
        lambda files, **kwargs: {"repositoryContext": kwargs["repository_context"]},
    )
    monkeypatch.setattr(repository_scan.tool_summaries, "refresh", lambda *_args: 1)

    repository_scan.scan_tool("example-tool", {"repository": "https://github.com/example/tool"})

    with db.session_scope() as s:
        report = s.execute(
            select(SourceAnalysisReport).where(SourceAnalysisReport.tool_name == "example-tool")
        ).scalar_one()
    repository = report.report["repositoryContext"]["repository"]
    assert repository["branch"] == "main"
    assert repository["lastCommitAt"] == "2025-02-03T04:05:06Z"
    assert not {"commitCount", "contributorCount"} & set(repository)


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
        _cached_tool(s, "killed-mid-scan")
        _cached_tool(s, "never-seen")
        _cached_tool(s, "checked-recently")
        s.add(RepositoryAnalysisState(tool_name="killed-mid-scan", status="pending", checked_at=None))
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
    assert names == ["never-seen", "killed-mid-scan", "checked-recently"]


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
    repository_scan._git(["-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init"], cwd=origin)
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


def test_clone_leaves_filtered_blobs_not_fetched(tmp_path):
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
    repository_scan._git(["-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init"], cwd=origin)

    checkout = tmp_path / "checkout"
    repository_scan.clone_repository(f"file://{origin}", checkout)
    files = repository_scan._read_repository_tree(checkout)

    assert len(files) == repository_scan.MAX_FILES
    assert [entry["path"] for entry in files] == [f"mod{index:03d}.py" for index in range(10, 130)]


def test_read_tree_spends_a_short_budget_on_the_code_not_the_reading(monkeypatch, tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    repository_scan._git(["init", "-q", "--initial-branch=main", "."], cwd=origin)
    repository_scan._git(["config", "uploadpack.allowFilter", "true"], cwd=origin)
    (origin / "docs").mkdir()
    (origin / "docs" / "guide.md").write_text("Download from https://packages.example.org/tool\n", encoding="utf-8")
    (origin / "src").mkdir()
    (origin / "src" / "client.py").write_text("requests.get('https://api.acme-data.org/v1')\n", encoding="utf-8")
    repository_scan._git(["add", "-A"], cwd=origin)
    repository_scan._git(["-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init"], cwd=origin)

    checkout = tmp_path / "checkout"
    repository_scan.clone_repository(f"file://{origin}", checkout)
    # Git lists a tree in path order, which would spend the one slot on the docs.
    # The scanner and the local reader have to agree on which file is worth it.
    monkeypatch.setattr(repository_scan, "MAX_FILES", 1)
    files = repository_scan._read_repository_tree(checkout)

    assert [entry["path"] for entry in files] == ["src/client.py"]


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


def _analyzed_report(session, name):
    user = repository_scan._scanner_user(session)
    report = SourceAnalysisReport(
        user_id=user.id,
        created_by_user_id=user.id,
        tool_name=name,
        source_label=f"https://github.com/example/{name}",
        report={"toolName": name},
        review_status=repository_scan.REVIEW_APPROVED,
        reviewed_at=datetime.now(tz=UTC).replace(tzinfo=None),
        source=repository_scan.SOURCE_REPOSITORY_SCAN,
        sync_status=repository_scan.SYNC_EVOLVED_REAL,
    )
    session.add(report)
    session.flush()
    return report.id


def test_partition_splits_backlog_from_refresh_and_drops_settled_work():
    """Continuous mode paces the two lanes differently, so it needs them apart.

    An hourly batch could afford to reselect an unsupported host or a repository
    still in backoff and cheaply re-decide it. At one candidate per second those
    would occupy the backlog lane permanently and the real work behind them
    would never start.
    """
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    with db.session_scope() as s:
        for name in (
            "never-scanned",
            "failed-and-due",
            "failed-in-backoff",
            "unsupported-settled",
            "analyzed",
            "analyzed-without-report",
        ):
            _cached_tool(s, name)
        s.add(
            RepositoryAnalysisState(
                tool_name="failed-and-due",
                status="error",
                checked_at=now - timedelta(hours=2),
                next_attempt_at=now - timedelta(minutes=1),
            )
        )
        s.add(
            RepositoryAnalysisState(
                tool_name="failed-in-backoff",
                status="error",
                checked_at=now - timedelta(hours=2),
                next_attempt_at=now + timedelta(hours=1),
            )
        )
        s.add(
            RepositoryAnalysisState(
                tool_name="unsupported-settled",
                status="unsupported",
                repository_url="https://github.com/example/unsupported-settled",
                checked_at=now - timedelta(hours=2),
            )
        )
        s.add(
            RepositoryAnalysisState(
                tool_name="analyzed",
                status="analyzed",
                report_id=_analyzed_report(s, "analyzed"),
                checked_at=now - timedelta(hours=3),
            )
        )
        # "analyzed" without a report row is not analyzed; it needs real work.
        s.add(
            RepositoryAnalysisState(
                tool_name="analyzed-without-report",
                status="analyzed",
                report_id=None,
                checked_at=now - timedelta(hours=1),
            )
        )

    backlog, refresh = repository_scan.partition_candidates()

    assert [name for name, _record in backlog] == [
        "never-scanned",
        "failed-and-due",
        "analyzed-without-report",
    ]
    assert [name for name, _record in refresh] == ["analyzed"]


def test_a_settled_unsupported_verdict_is_reconsidered_when_the_url_moves():
    with db.session_scope() as s:
        _cached_tool(s, "moved")
        s.add(
            RepositoryAnalysisState(
                tool_name="moved",
                status="unsupported",
                repository_url="https://internal.example/moved",
                checked_at=datetime.now(tz=UTC).replace(tzinfo=None),
            )
        )

    backlog, _refresh = repository_scan.partition_candidates()

    assert [name for name, _record in backlog] == ["moved"]


class _Clock:
    """A monotonic clock the loop drives forward only by sleeping."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.0)


def _paced_run(monkeypatch, *, backlog, refresh, stop_after, scan=None):
    clock = _Clock()
    monkeypatch.setattr(repository_scan, "time", clock)
    passes = []

    def fake_partition(depth):
        passes.append(clock.now)
        return (list(backlog), list(refresh))

    monkeypatch.setattr(repository_scan, "partition_candidates", fake_partition)
    scanned = []

    def record(name, record_, results, *, force):
        scanned.append(name)
        if scan is not None:
            scan(clock)
        results["analyzed"] += 1
        return "analyzed"

    monkeypatch.setattr(repository_scan, "_scan_one", record)
    summary = repository_scan.run_continuous(
        pace=repository_scan.ScanPace(heartbeat=1e9),
        should_stop=lambda: len(scanned) >= stop_after,
    )
    return summary, scanned, passes, clock


def test_continuous_paces_the_two_lanes_independently(monkeypatch):
    summary, scanned, _passes, clock = _paced_run(
        monkeypatch,
        backlog=[(f"b{index}", {}) for index in range(200)],
        refresh=[(f"r{index}", {}) for index in range(200)],
        stop_after=70,
    )

    # Backlog starts at t=0,1,2,... and refresh at t=0 and t=60, so 70 scans
    # land at t=67: 68 backlog and 2 refresh.
    assert clock.now == pytest.approx(67.0)
    assert summary["backlog_scanned"] == 68
    assert summary["refresh_scanned"] == 2
    assert scanned[:3] == ["b0", "r0", "b1"]


def test_a_slow_backlog_clone_delays_the_next_start_but_cannot_starve_refresh(monkeypatch):
    """Each interval is a minimum spacing between starts, not a guarantee."""

    def slow(clock):
        clock.now += 10.0

    summary, scanned, _passes, _clock = _paced_run(
        monkeypatch,
        backlog=[(f"b{index}", {}) for index in range(200)],
        refresh=[(f"r{index}", {}) for index in range(200)],
        stop_after=20,
        scan=slow,
    )

    # Ten seconds a tool against a one-second interval means the backlog lane is
    # permanently overdue, yet refresh still gets its turn: it waits at most for
    # the single tool in flight.
    assert summary["refresh_scanned"] > 1
    assert summary["backlog_scanned"] + summary["refresh_scanned"] == 20
    assert scanned.count("r0") == 1


def test_an_empty_lane_waits_for_the_next_catalog_pass_instead_of_spinning(monkeypatch):
    _summary, _scanned, passes, clock = _paced_run(
        monkeypatch,
        backlog=[],
        refresh=[(f"r{index}", {}) for index in range(200)],
        stop_after=30,
    )

    # 30 refresh scans span roughly 29 minutes. A backlog lane that retried at
    # its own one-second interval would have forced a catalog pass every second;
    # bounded by the 300s refill it takes single digits.
    assert clock.now > 1500
    assert len(passes) <= 8


def test_scan_tool_stamps_the_attempt_before_it_clones(monkeypatch):
    """A pod killed mid-clone leaves no other trace of having tried.

    Ordering puts a row with no checked_at first, so every restart reselected
    the same repository and died on it again. A scheduled job needed an operator
    to break that; a continuous one would spin on it.
    """
    observed = []

    def exploding_clone(_url, _dest):
        with db.session_scope() as s:
            observed.append(s.get(RepositoryAnalysisState, "poison").checked_at)
        raise repository_scan.RepositoryScanError("killed while cloning")

    monkeypatch.setattr(repository_scan, "repository_head", lambda _url: "a" * 40)
    monkeypatch.setattr(repository_scan, "clone_repository", exploding_clone)

    result = repository_scan.scan_tool("poison", {"repository": "https://github.com/example/poison"})

    assert result == "error"
    assert observed[0] is not None, "the clone ran against a row that still looked never-checked"


def test_the_heartbeat_period_matches_what_workers_expects():
    """/workers has no cron line to read a continuous job's period from, so it
    uses the heartbeat instead. If the two drift, a perfectly healthy worker is
    reported late or a dead one is reported healthy."""
    assert repository_scan.HEARTBEAT_SECONDS == job_catalog.CONTINUOUS_HEARTBEAT_MINUTES * 60


def test_continuous_publishes_a_run_so_the_worker_is_not_reported_absent(monkeypatch):
    """job_guard.sh records a run when a scheduled child exits. A process that
    never exits has no such boundary, and /workers would show the job as never
    having run at all."""
    _summary, _scanned, _passes, _clock = _paced_run(
        monkeypatch,
        backlog=[(f"b{index}", {}) for index in range(50)],
        refresh=[],
        stop_after=5,
    )

    with db.session_scope() as s:
        runs = list(s.execute(select(JobRun).where(JobRun.job_name == "repository-analysis")).scalars())

    assert len(runs) == 1
    assert runs[0].succeeded is True


# --- Host facts in the scanner's report context -----------------------------
#
# The scanner clones --depth 1, so _local_git_context always measures one
# commit by one author. Those two numbers cost every scanned tool 20
# maintenance points until the enrichment lane supplies the real ones.

SHALLOW = {"repository": {"contributorCount": 1, "commitCount": 1, "branch": "main"}}
SCAN_URL = "https://github.com/example/tool"


def _host_row(url=SCAN_URL, **fields):
    import repository_enrichment
    from backend.models import RepositoryHostMetadata

    with db.session_scope() as s:
        s.add(
            RepositoryHostMetadata(
                url_hash=repository_enrichment.url_hash(url),
                repository_url=url,
                provider="github",
                api="github",
                kind="forge",
                project_path="example/tool",
                status="current",
                attempts=0,
                topics=[],
                **fields,
            )
        )


def _context(measured=SHALLOW, record=None):
    # What acquisition measured, which is what _report_context merges: a clone
    # and a wiki page set both hand it {"repository": {...}}.
    return repository_scan._report_context(
        measured,
        url=SCAN_URL,
        provider="github",
        commit_sha="abc123",
        record=record or {},
    )


def test_the_shallow_clones_counts_are_dropped_when_no_host_facts_exist():
    # Absent is honest; 1 is a measurement of our own clone flags. The
    # assessment treats absent as "not known" and deducts nothing.
    repository = _context()["repository"]
    assert "contributorCount" not in repository
    assert "commitCount" not in repository
    assert repository["branch"] == "main"


def test_the_host_counts_replace_the_clones():
    _host_row(contributor_count=14, commit_count=920)
    repository = _context()["repository"]
    assert repository["contributorCount"] == 14
    assert repository["commitCount"] == 920


def test_a_host_that_publishes_only_one_of_the_two_supplies_only_that_one():
    # Bitbucket, Forgejo and Gerrit expose neither count; a partially filled
    # row must not resurrect the clone's number for the missing half.
    _host_row(contributor_count=None, commit_count=41)
    repository = _context()["repository"]
    assert "contributorCount" not in repository
    assert repository["commitCount"] == 41


def test_the_scanners_other_overrides_are_unchanged():
    _host_row(contributor_count=2, commit_count=7)
    repository = _context()["repository"]
    assert repository["url"] == SCAN_URL
    assert repository["provider"] == "github"
    assert repository["commitSha"] == "abc123"
    # The checkout is always freshly cloned, so it is never dirty.
    assert repository["dirty"] is False


def test_a_context_without_a_repository_block_still_gets_host_counts():
    _host_row(contributor_count=5, commit_count=300)
    repository = repository_scan._report_context({}, url=SCAN_URL, provider="github", commit_sha="abc123", record={})[
        "repository"
    ]
    assert repository["contributorCount"] == 5


def _activity(context):
    from backend.source_analyzer import analyze_source_files

    report = analyze_source_files(
        [{"path": "tool.py", "content": "print('hello')\n"}],
        tool_name="example-tool",
        source_label=SCAN_URL,
        repository_context=context,
    )
    for assessment in report["assessments"]:
        if assessment["key"] == "maintenance-activity":
            return assessment
    raise AssertionError("no maintenance-activity assessment")


def test_a_scan_no_longer_deducts_twenty_points_for_its_own_clone_flags():
    # The defect this whole lane exists to fix: every scanned repository lost
    # ten points for being "single-contributor" and ten for a "very small
    # commit history", both read off a --depth 1 checkout.
    labels = {signal["label"] for signal in _activity(_context())["signals"]}
    assert "Single-contributor repository" not in labels
    assert "Very small commit history" not in labels


def test_a_genuinely_single_contributor_repository_is_still_flagged():
    # Dropping the clone's guess must not make the signal unreachable: when a
    # host says one contributor, that is a real fact and still scores.
    _host_row(contributor_count=1, commit_count=2)
    labels = {signal["label"] for signal in _activity(_context())["signals"]}
    assert "Single-contributor repository" in labels
    assert "Very small commit history" in labels


# --- Archived is a terminal activity status ---------------------------------


def _maintenance(context):
    from backend.source_analyzer import analyze_source_files

    report = analyze_source_files(
        [{"path": "tool.py", "content": "print('hello')\n"}],
        tool_name="example-tool",
        source_label=SCAN_URL,
        repository_context=context,
    )
    return report["repositoryContext"]["maintenance"], report


def _fresh(**extra):
    # _last_commit_age_days needs both ends of the interval; _local_git_context
    # supplies analyzedAt in the real scanner path.
    now = datetime.now(UTC)
    return {
        "repository": {
            "lastCommitAt": (now - timedelta(days=3)).isoformat(),
            "analyzedAt": now.isoformat(),
            **extra,
        }
    }


def test_the_host_archive_flag_reaches_the_analyzer():
    # REPOSITORY_CONTEXT_REPOSITORY_KEYS strips anything not listed, so an
    # unlisted key would vanish silently between the scanner and the score.
    _host_row(archived=True)
    assert _context(_fresh())["repository"]["archived"] is True


def test_a_host_that_says_not_archived_is_recorded_as_false():
    # False is a fact; only None means the host has no such field.
    _host_row(archived=False)
    assert _context(_fresh())["repository"]["archived"] is False


def test_a_host_without_an_archive_field_leaves_the_key_absent():
    # Bitbucket has no archive concept at all.
    _host_row(archived=None)
    assert "archived" not in _context(_fresh())["repository"]


def test_archived_outranks_a_recent_commit():
    # The repository was pushed three days ago and archived after that, which
    # is the ordinary shape: the last act before archiving is often a commit.
    _host_row(archived=True)
    maintenance, _report = _maintenance(_context(_fresh()))
    assert maintenance["status"] == "archived"
    assert maintenance["archived"] is True


def test_archived_is_not_stale():
    # Stale means work was expected and did not arrive. Archived means no work
    # is expected, so the outreach paths keyed on this flag must not fire.
    _host_row(archived=True)
    maintenance, _report = _maintenance(_context(_fresh()))
    assert maintenance["stale"] is False


def test_a_live_repository_keeps_its_age_derived_status():
    _host_row(archived=False)
    maintenance, _report = _maintenance(_context(_fresh()))
    assert maintenance["status"] == "active"
    assert maintenance["archived"] is False


def test_archived_scores_as_harshly_as_dormant():
    _host_row(archived=True)
    activity = _activity(_context(_fresh()))
    labels = {signal["label"] for signal in activity["signals"]}
    assert "Repository is archived (read-only)" in labels
    assert "Recent repository activity" not in labels
    assert "Find a maintained alternative." in activity["recommendations"]


def test_archived_reports_a_terminal_stewardship_status():
    # Without this it fell through to "watch", which reads as "we are worried
    # about this" when the repository is simply closed.
    _host_row(archived=True)
    _maintenance_ctx, report = _maintenance(_context(_fresh()))
    assert report["healthCore"]["stewardshipStatus"] == "archived"
    assert report["healthCore"]["sourceMaintenanceStatus"] == "archived"


def test_the_archived_signal_survives_signal_truncation():
    _host_row(archived=True, contributor_count=9, commit_count=800)
    maintenance, _report = _maintenance(_context(_fresh()))
    assert {"kind": "archived", "value": True} in maintenance["signals"]


# --- The maintainer's declared lifecycle ------------------------------------
#
# deprecated and replaced_by are toolinfo fields a maintainer sets by hand.
# They are testimony, not evidence: nothing in a checkout can confirm or
# contradict them, so they travel in their own context block rather than
# alongside the facts we measured.

DEPRECATED = {"deprecated": True}
SUCCESSOR = "https://toolhub.wikimedia.org/tools/successor"
SUPERSEDED = {"deprecated": True, "replaced_by": SUCCESSOR}


def _dormant():
    now = datetime.now(UTC)
    return {
        "repository": {
            "lastCommitAt": (now - timedelta(days=1200)).isoformat(),
            "analyzedAt": now.isoformat(),
        }
    }


def test_the_catalogue_record_reaches_the_analyzer_as_lifecycle():
    _host_row()
    _maintenance_ctx, report = _maintenance(_context(_fresh(), record=SUPERSEDED))
    assert report["repositoryContext"]["lifecycle"] == {"deprecated": True, "replacedBy": SUCCESSOR}


def test_an_undeclared_lifecycle_keeps_the_negative_and_drops_the_empty_successor():
    # False is a measurement -- the maintainer did not retire this tool. An
    # empty replacedBy is not, so it must not survive as a falsy successor.
    _host_row()
    _maintenance_ctx, report = _maintenance(_context(_fresh(), record={}))
    assert report["repositoryContext"]["lifecycle"] == {"deprecated": False}


def test_a_blank_replaced_by_is_not_a_successor():
    _host_row()
    _maintenance_ctx, report = _maintenance(_context(_fresh(), record={"replaced_by": "   "}))
    assert report["healthCore"]["replacedBy"] == ""
    assert report["healthCore"]["stewardshipStatus"] != "superseded"


def test_a_recorded_successor_becomes_the_stewardship_status():
    _host_row(archived=False)
    _maintenance_ctx, report = _maintenance(_context(_fresh(), record=SUPERSEDED))
    assert report["healthCore"]["stewardshipStatus"] == "superseded"
    assert report["healthCore"]["replacedBy"] == SUCCESSOR


def test_a_successor_outranks_the_archive_flag():
    # Both are terminal, but only one answers "what should I use instead".
    _host_row(archived=True)
    _maintenance_ctx, report = _maintenance(_context(_fresh(), record=SUPERSEDED))
    assert report["healthCore"]["sourceMaintenanceStatus"] == "archived"
    assert report["healthCore"]["stewardshipStatus"] == "superseded"


def test_deprecated_without_a_successor_is_its_own_status():
    _host_row(archived=False)
    _maintenance_ctx, report = _maintenance(_context(_fresh(), record=DEPRECATED))
    assert report["healthCore"]["stewardshipStatus"] == "deprecated"
    assert report["healthCore"]["replacedBy"] == ""


def test_an_archived_repository_with_a_successor_points_at_it_instead_of_nowhere():
    _host_row(archived=True)
    activity = _activity(_context(_fresh(), record=SUPERSEDED))
    assert activity["recommendations"] == [f"Use the recorded replacement: {SUCCESSOR}"]


def test_an_archived_repository_without_one_still_says_find_an_alternative():
    _host_row(archived=True)
    activity = _activity(_context(_fresh(), record={}))
    assert "Find a maintained alternative." in activity["recommendations"]


def test_a_dormant_repository_with_a_successor_stops_asking_for_outreach():
    # Outreach about a tool the maintainer already replaced wastes both sides'
    # time, and the answer is already in the catalogue.
    _host_row(archived=False)
    activity = _activity(_context(_dormant(), record=SUPERSEDED))
    assert activity["recommendations"] == [f"Use the recorded replacement: {SUCCESSOR}"]


def test_a_dormant_repository_without_one_still_asks_for_outreach():
    _host_row(archived=False)
    activity = _activity(_context(_dormant(), record={}))
    assert "Flag the tool for maintainer outreach or archival review." in activity["recommendations"]


def test_the_successor_is_a_signal_that_changes_no_score():
    # Archived costs 35 points by deliberate policy. Recording a successor
    # improves the advice, not the arithmetic.
    _host_row(archived=True)
    without = _activity(_context(_fresh(), record={}))
    with_successor = _activity(_context(_fresh(), record=SUPERSEDED))
    added = {item["label"] for item in with_successor["signals"]} - {item["label"] for item in without["signals"]}
    assert added == {"Replacement tool recorded"}
    assert with_successor["score"] == without["score"]


# --- wiki-hosted source ------------------------------------------------------

SCRIPT_URL = "https://en.wikipedia.org/wiki/User:Example/twinkle.js"
GADGET_URL = "https://en.wikipedia.org/wiki/MediaWiki:Gadget-Twinkle.js"

DEFINITION = "== Browsing ==\n* Twinkle[ResourceLoader|rights=autoconfirmed]|Twinkle.js|morebits.js\n"


def _wiki_page(title, revid=1, timestamp="2024-06-01T00:00:00Z", content="var a = 1;"):
    return {
        "ns": 2,
        "title": title,
        "revisions": [{"revid": revid, "timestamp": timestamp, "slots": {"main": {"content": content}}}],
    }


def _wiki_answers(monkeypatch, answers):
    """Answer Action API queries from canned payloads, recording every request.

    Keys are substrings that survive percent-encoding, so a query is matched by
    what it asks for rather than by the exact spelling of its query string.
    """
    calls = []

    def fake_fetch(_session, url, *, policy, caller):
        assert policy is repository_scan.outbound.WIKI_API
        assert "toolhub-evolved" in caller.user_agent
        calls.append(url)
        for marker, payload in answers.items():
            if marker in url:
                return json.dumps(payload).encode("utf-8")
        pytest.fail(f"unexpected query: {url}")

    monkeypatch.setattr(repository_scan.outbound, "fetch_bounded", fake_fetch)
    # A wiki page has no clone, and reaching for one would mean the scanner
    # took the forge path for a URL that is not a repository.
    monkeypatch.setattr(
        repository_scan, "clone_repository", lambda *_a: pytest.fail("a wiki page must never be cloned")
    )
    monkeypatch.setattr(
        repository_scan, "repository_head", lambda *_a: pytest.fail("a wiki page has no remote HEAD to ask for")
    )
    monkeypatch.setattr(
        repository_scan,
        "analyze_source_files",
        lambda files, **kwargs: {
            "filesAnalyzed": len(files),
            "healthCore": {"score": 80, "grade": "good"},
            "analyzedPaths": [file["path"] for file in files],
            "repositoryContext": kwargs["repository_context"],
        },
    )
    monkeypatch.setattr(repository_scan.tool_summaries, "refresh", lambda *_args: 1)
    return calls


def _scan_wiki(url, name="wiki-tool"):
    return repository_scan.scan_tool(name, {"repository": url})


def _stored_report(name="wiki-tool"):
    with db.session_scope() as s:
        return s.execute(select(SourceAnalysisReport).where(SourceAnalysisReport.tool_name == name)).scalar_one().report


def test_both_spellings_of_a_wiki_page_url_normalize_to_one():
    # toolinfo carries /wiki/X and index.php?title=X, and the same gadget must
    # not be scanned twice under two keys.
    assert repository_scan.repository_url(SCRIPT_URL) == SCRIPT_URL
    assert repository_scan.repository_url("https://en.wikipedia.org/w/index.php?title=User:Example/twinkle.js") == (
        SCRIPT_URL
    )
    assert repository_scan.repository_url("https://en.wikipedia.org/wiki/User:Example/twinkle.js") == SCRIPT_URL


def test_a_wiki_page_reports_the_mediawiki_provider():
    assert repository_scan.provider_for(GADGET_URL) == "mediawiki-wikimedia"


@pytest.mark.parametrize(
    "url",
    [
        # Prose about a tool is not the tool.
        "https://en.wikipedia.org/wiki/User:Example/documentation",
        "https://en.wikipedia.org/wiki/Twinkle",
        # The wiki allowlist is the same one identity verification uses.
        "https://wiki.example.org/wiki/MediaWiki:Gadget-Foo.js",
        "http://en.wikipedia.org/wiki/User:Example/twinkle.js",
    ],
)
def test_a_wiki_url_that_is_not_source_is_still_refused(url):
    assert repository_scan.repository_url(url) == ""


def test_a_user_script_and_its_subpages_cost_one_request(monkeypatch):
    calls = _wiki_answers(
        monkeypatch,
        {
            "generator=allpages": {
                "query": {
                    "pages": [
                        _wiki_page("User:Example/twinkle.js", revid=10),
                        _wiki_page("User:Example/twinkle.css", revid=11, content="a{}"),
                    ]
                }
            }
        },
    )

    assert _scan_wiki(SCRIPT_URL) == "analyzed"
    # The prefix search is a generator feeding the revision fetch, so finding
    # the subpages costs nothing beyond reading them.
    assert len(calls) == 1
    assert _stored_report()["analyzedPaths"] == ["User:Example/twinkle.css", "User:Example/twinkle.js"]


def test_the_analyzed_path_is_the_page_title_a_maintainer_can_search_for(monkeypatch):
    _wiki_answers(monkeypatch, {"generator=allpages": {"query": {"pages": [_wiki_page("User:Example/twinkle.js")]}}})
    _scan_wiki(SCRIPT_URL)
    assert _stored_report()["analyzedPaths"] == ["User:Example/twinkle.js"]


def test_a_neighboring_tool_is_returned_by_the_search_but_not_analyzed(monkeypatch):
    # apprefix=Example/twinkle also matches twinkleblock.js, a different tool
    # by the same author. Analyzing it here would file one author's second tool
    # under their first.
    _wiki_answers(
        monkeypatch,
        {
            "generator=allpages": {
                "query": {
                    "pages": [
                        _wiki_page("User:Example/twinkle.js"),
                        _wiki_page("User:Example/twinkleblock.js"),
                    ]
                }
            }
        },
    )

    assert _scan_wiki(SCRIPT_URL) == "analyzed"
    assert _stored_report()["analyzedPaths"] == ["User:Example/twinkle.js"]


def test_a_gadget_costs_two_requests_and_pulls_in_every_file_it_declares(monkeypatch):
    calls = _wiki_answers(
        monkeypatch,
        {
            "Gadgets-definition": {
                "query": {"pages": [_wiki_page("MediaWiki:Gadgets-definition", content=DEFINITION)]}
            },
            "action=query": {
                "query": {
                    "pages": [
                        _wiki_page("MediaWiki:Gadget-Twinkle.js", revid=20),
                        _wiki_page("MediaWiki:Gadget-morebits.js", revid=21),
                    ]
                }
            },
        },
    )

    assert _scan_wiki(GADGET_URL) == "analyzed"
    # One to learn what the gadget consists of, one to read it.
    assert len(calls) == 2
    assert _stored_report()["analyzedPaths"] == ["MediaWiki:Gadget-Twinkle.js", "MediaWiki:Gadget-morebits.js"]


def test_an_unregistered_gadget_page_is_scanned_alone_rather_than_guessed_at(monkeypatch):
    _wiki_answers(
        monkeypatch,
        {
            "Gadgets-definition": {
                "query": {"pages": [_wiki_page("MediaWiki:Gadgets-definition", content="* X[RL]|X.js")]}
            },
            "action=query": {"query": {"pages": [_wiki_page("MediaWiki:Gadget-Twinkle.js")]}},
        },
    )

    assert _scan_wiki(GADGET_URL) == "analyzed"
    assert _stored_report()["analyzedPaths"] == ["MediaWiki:Gadget-Twinkle.js"]


def test_an_unchanged_page_set_is_skipped_on_the_next_pass(monkeypatch):
    answers = {"generator=allpages": {"query": {"pages": [_wiki_page("User:Example/twinkle.js", revid=10)]}}}
    _wiki_answers(monkeypatch, answers)

    assert _scan_wiki(SCRIPT_URL) == "analyzed"
    # The fetch still happens -- a page set has no cheap head -- but the
    # analysis and the report row do not.
    assert _scan_wiki(SCRIPT_URL) == "skipped"
    with db.session_scope() as s:
        assert len(s.execute(select(SourceAnalysisReport)).scalars().all()) == 1


def test_an_edit_to_a_helper_page_rescans_the_whole_tool(monkeypatch):
    # The entry page is untouched. A head that tracked only the page we were
    # pointed at would never notice this.
    def answers(helper_revid):
        return {
            "generator=allpages": {
                "query": {
                    "pages": [
                        _wiki_page("User:Example/twinkle.js", revid=10),
                        _wiki_page("User:Example/twinkle/core.js", revid=helper_revid),
                    ]
                }
            }
        }

    _wiki_answers(monkeypatch, answers(1))
    assert _scan_wiki(SCRIPT_URL) == "analyzed"
    _wiki_answers(monkeypatch, answers(2))
    assert _scan_wiki(SCRIPT_URL) == "analyzed"


def test_a_lagged_or_throttled_wiki_is_an_error_not_a_tool_with_no_source(monkeypatch):
    # The Action API answers HTTP 200 with an error object. Reading that as an
    # empty result would store a report claiming the tool has no code.
    _wiki_answers(monkeypatch, {"generator=allpages": {"error": {"code": "maxlag", "info": "Waiting for a replica"}}})

    assert _scan_wiki(SCRIPT_URL) == "error"
    with db.session_scope() as s:
        state = s.get(RepositoryAnalysisState, "wiki-tool")
        assert state.status == "error"
        assert "maxlag" in state.last_error
        # Retried later rather than settled as unsupported.
        assert state.next_attempt_at is not None


def test_a_page_set_that_holds_no_revision_is_an_error_not_an_empty_report(monkeypatch):
    _wiki_answers(
        monkeypatch,
        {"generator=allpages": {"query": {"pages": [{"ns": 2, "title": "User:Example/twinkle.js", "missing": True}]}}},
    )

    assert _scan_wiki(SCRIPT_URL) == "error"
    with db.session_scope() as s:
        assert s.execute(select(SourceAnalysisReport)).scalars().all() == []


def test_the_report_dates_the_source_by_its_most_recent_edit(monkeypatch):
    _wiki_answers(
        monkeypatch,
        {
            "generator=allpages": {
                "query": {
                    "pages": [
                        _wiki_page("User:Example/twinkle.js", timestamp="2019-01-01T00:00:00Z"),
                        _wiki_page("User:Example/twinkle.css", timestamp="2025-02-03T04:05:06Z", content="a{}"),
                    ]
                }
            }
        },
    )
    _scan_wiki(SCRIPT_URL)

    repository = _stored_report()["repositoryContext"]["repository"]
    assert repository["lastCommitAt"] == "2025-02-03T04:05:06Z"
    assert repository["provider"] == "mediawiki-wikimedia"
    assert repository["url"] == SCRIPT_URL
    # A wiki page has no branch, no tag and no default branch. An absent key
    # reads as "not measured" downstream, where a made-up one would be scored.
    assert not {"branch", "tag", "defaultBranch"} & set(repository)


def test_a_page_larger_than_the_analyzer_cap_is_dropped_not_truncated(monkeypatch):
    _wiki_answers(
        monkeypatch,
        {
            "generator=allpages": {
                "query": {
                    "pages": [
                        _wiki_page("User:Example/twinkle.js", content="x" * (repository_scan.MAX_FILE_BYTES + 1)),
                        _wiki_page("User:Example/twinkle.css", content="a{}"),
                    ]
                }
            }
        },
    )
    _scan_wiki(SCRIPT_URL)
    assert _stored_report()["analyzedPaths"] == ["User:Example/twinkle.css"]
