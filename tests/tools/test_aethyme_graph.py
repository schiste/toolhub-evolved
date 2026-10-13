# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO

import pytest

SOURCE_SHA = "a" * 40
OTHER_SHA = "b" * 40

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import aethyme_graph


def _write_engine_pin(repo: Path, version: str = "0.8.26") -> None:
    pin = repo / ".aethyme" / "engine-version"
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text(f"{version}\n", encoding="utf-8")


def _refresh_plan(
    *,
    safe_to_execute: bool = True,
    authority: str = "committed_fragments",
    pinned: str = "0.8.26",
    installed: str = "0.8.26",
    changed_file_count: int = 0,
) -> dict[str, object]:
    return {
        "plan_sha256": "f" * 64,
        "canonical_repository": "schiste/toolhub-evolved",
        "policy": {
            "authority": authority,
            "repository": "schiste/toolhub-evolved",
            "pinned_engine_version": pinned,
        },
        "installed": {
            "router_version": installed,
            "linked_engine_version": installed,
            "graph_indexer_version": installed,
        },
        "fragments": {"changed_file_count": changed_file_count},
        "derived_store": {"action": "materialize_after_fragment_verification"},
        "safe_to_execute": safe_to_execute,
        "blockers": [] if safe_to_execute else ["broker sessions live"],
    }


def _materialized_graph_status() -> dict[str, object]:
    return {
        "healthy": True,
        "compatibility": "compatible",
        "source": {"head_sha": SOURCE_SHA},
        "fragments": {
            "status": "passed",
            "changed_file_count": 0,
            "working_tree_matches_proposal": True,
        },
        "derived_store": {"status": "current", "indexed_commit": SOURCE_SHA},
    }


def test_plan_prints_reviewable_diff_without_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_engine_pin(tmp_path)
    plan = _refresh_plan()
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []

    diff = f"Graph refresh plan\n  plan SHA-256: {'f' * 64}\nGraph fragment changes (hash-only):\n  none\n"

    def write_plan(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        assert stdout is not None
        if "--json" in args:
            json.dump(plan, stdout)
            stdout.flush()
        elif "--diff" in args:
            stdout.write(diff)
            stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_plan)
    assert aethyme_graph.plan_refresh(tmp_path) == plan
    output = capsys.readouterr().out
    assert "Graph fragment changes (hash-only)" in output
    assert f"--confirm {'f' * 64}" in output
    assert len(calls) == 2
    assert all(args[1:4] == ["graph", "refresh", "plan"] for args in calls)
    assert "execute" not in output


def test_apply_requires_the_digest_from_the_reviewed_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_engine_pin(tmp_path)
    plan = _refresh_plan()
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []

    def write_plan(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        if "--json" in args:
            assert stdout is not None
            json.dump(plan, stdout)
            stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_plan)
    assert aethyme_graph.apply_refresh(tmp_path, "f" * 64) == plan
    assert len(calls) == 2
    assert calls[0][1:4] == ["graph", "refresh", "plan"]
    assert calls[1] == ["aethyme", "graph", "refresh", "execute", "--repo", str(tmp_path), "--confirm", "f" * 64]


def test_apply_rejects_an_unreviewed_digest_without_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_engine_pin(tmp_path)
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []

    def write_plan(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        assert stdout is not None
        json.dump(_refresh_plan(), stdout)
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_plan)
    with pytest.raises(RuntimeError, match="does not match the reviewed plan"):
        aethyme_graph.apply_refresh(tmp_path, "0" * 64)
    assert len(calls) == 1


def test_check_refuses_stale_fragments_without_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_engine_pin(tmp_path)
    plan = _refresh_plan(changed_file_count=2)
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []

    def write_plan(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        assert stdout is not None
        json.dump(plan, stdout)
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_plan)
    with pytest.raises(RuntimeError, match="fragments are stale"):
        aethyme_graph.check_graph(tmp_path)
    assert len(calls) == 1
    assert calls[0][1:4] == ["graph", "refresh", "plan"]


def test_check_materializes_current_fragments_and_smoke_tests_explore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_engine_pin(tmp_path)
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []

    def run_aethyme(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        if "--json" in args and args[1:4] == ["graph", "refresh", "plan"]:
            assert stdout is not None
            json.dump(_refresh_plan(), stdout)
            stdout.flush()
        elif args[1:3] == ["graph", "status"]:
            assert stdout is not None
            json.dump(
                {
                    "healthy": True,
                    "compatibility": "compatible",
                    "source": {"head_sha": SOURCE_SHA},
                    "fragments": {
                        "status": "passed",
                        "changed_file_count": 0,
                        "working_tree_matches_proposal": True,
                    },
                    "derived_store": {"status": "current", "indexed_commit": SOURCE_SHA},
                },
                stdout,
            )
            stdout.flush()
        elif args[1:3] == ["graph", "overview"]:
            assert stdout is not None
            json.dump({"code_areas": ["proxy"], "representative_code_files": ["proxy/app.py"]}, stdout)
            stdout.flush()
        elif args[1:3] == ["explore", "--repo"]:
            assert stdout is not None
            json.dump(
                {
                    "status": "complete",
                    "safe_to_use_as_navigation": True,
                    "answer": [{"summary": "proxy/app.py"}],
                    "observability": {"readiness": {"fresh_enough": True, "graph_freshness_status": "fresh"}},
                },
                stdout,
            )
            stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", run_aethyme)
    aethyme_graph.check_graph(tmp_path)
    assert calls[0][1:4] == ["graph", "refresh", "plan"]
    assert calls[1] == ["aethyme", "graph", "materialize", "--repo", str(tmp_path)]
    assert calls[2][1:3] == ["graph", "status"]
    assert calls[3][1:3] == ["graph", "overview"]
    assert calls[4][1:3] == ["explore", "--repo"]
    assert all("execute" not in args for args in calls)


@pytest.mark.parametrize(
    ("readiness", "expected_error"),
    [
        ({"fresh_enough": False, "graph_freshness_status": "unknown"}, None),
        ({"fresh_enough": False, "graph_freshness_status": "stale"}, "freshness is unverified"),
        ({"fresh_enough": True, "graph_freshness_status": "unknown"}, "freshness is unverified"),
    ],
)
def test_check_only_accepts_unknown_freshness_after_current_graph_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readiness: dict[str, object],
    expected_error: str | None,
) -> None:
    _write_engine_pin(tmp_path)
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []
    graph_status = _materialized_graph_status()
    graph_overview = {"code_areas": ["proxy"], "representative_code_files": ["proxy/app.py"]}

    def run_aethyme(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        if args[1:4] == ["graph", "refresh", "plan"]:
            assert stdout is not None
            json.dump(_refresh_plan(), stdout)
            stdout.flush()
        elif args[1:3] == ["graph", "materialize"]:
            return
        elif args[1:3] == ["graph", "status"]:
            assert stdout is not None
            json.dump(graph_status, stdout)
            stdout.flush()
        elif args[1:3] == ["graph", "overview"]:
            assert stdout is not None
            json.dump(graph_overview, stdout)
            stdout.flush()
        elif args[1:3] == ["explore", "--repo"]:
            assert stdout is not None
            json.dump(
                {
                    "status": "complete",
                    "safe_to_use_as_navigation": True,
                    "answer": [{"summary": "proxy/app.py"}],
                    "observability": {"readiness": readiness},
                },
                stdout,
            )
            stdout.flush()
        else:
            raise AssertionError(f"Unexpected Aethyme invocation: {args}")

    monkeypatch.setattr(aethyme_graph, "_run", run_aethyme)
    if expected_error is None:
        aethyme_graph.check_graph(tmp_path)
    else:
        with pytest.raises(RuntimeError, match=expected_error):
            aethyme_graph.check_graph(tmp_path)

    assert calls[0][1:4] == ["graph", "refresh", "plan"]
    assert calls[1][1:3] == ["graph", "materialize"]
    assert calls[2][1:3] == ["graph", "status"]
    assert calls[3][1:3] == ["graph", "overview"]
    assert calls[4][1:3] == ["explore", "--repo"]


@pytest.mark.parametrize(
    "overview",
    [
        {"code_areas": {"proxy": True}, "representative_code_files": "proxy/app.py"},
        {"code_areas": [], "representative_code_files": ["proxy/app.py"]},
        {"code_areas": [" "], "representative_code_files": ["proxy/app.py"]},
        {"code_areas": ["proxy", ""], "representative_code_files": ["proxy/app.py"]},
        {"code_areas": ["proxy"], "representative_code_files": []},
        {"code_areas": ["proxy"], "representative_code_files": ["proxy/app.py", " "]},
    ],
)
def test_verify_materialized_graph_rejects_malformed_overview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overview: dict[str, object]
) -> None:
    responses = iter([_materialized_graph_status(), overview])
    monkeypatch.setattr(aethyme_graph, "_read_json", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(RuntimeError, match="graph overview returned no repository navigation evidence"):
        aethyme_graph._verify_materialized_graph(tmp_path, "aethyme")


def test_verify_materialized_graph_rejects_a_store_indexed_at_another_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status = _materialized_graph_status()
    status["derived_store"] = {"status": "current", "indexed_commit": OTHER_SHA}
    monkeypatch.setattr(aethyme_graph, "_read_json", lambda *_args, **_kwargs: status)

    with pytest.raises(RuntimeError, match="derived graph store is not current"):
        aethyme_graph._verify_materialized_graph(tmp_path, "aethyme")


def test_verify_materialized_graph_rejects_boolean_fragment_change_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status = _materialized_graph_status()
    status["fragments"] = {
        "status": "passed",
        "changed_file_count": False,
        "working_tree_matches_proposal": True,
    }
    responses = iter(
        [status, {"code_areas": ["proxy"], "representative_code_files": ["proxy/app.py"]}]
    )
    monkeypatch.setattr(aethyme_graph, "_read_json", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(RuntimeError, match="graph fragments are not current"):
        aethyme_graph._verify_materialized_graph(tmp_path, "aethyme")


@pytest.mark.parametrize("source_sha", ["", "not-a-sha", "a" * 39, "A" * 40])
def test_verify_materialized_graph_rejects_invalid_source_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_sha: str
) -> None:
    status = _materialized_graph_status()
    status["source"] = {"head_sha": source_sha}
    status["derived_store"] = {"status": "current", "indexed_commit": source_sha}
    responses = iter(
        [status, {"code_areas": ["proxy"], "representative_code_files": ["proxy/app.py"]}]
    )
    monkeypatch.setattr(aethyme_graph, "_read_json", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(RuntimeError, match="full Git revision SHA"):
        aethyme_graph._verify_materialized_graph(tmp_path, "aethyme")


def test_rebuild_refuses_live_session_blocker_before_execute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_engine_pin(tmp_path)
    plan = _refresh_plan(safe_to_execute=False)
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []

    def write_blocked_plan(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        assert stdout is not None
        json.dump(plan, stdout)
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_blocked_plan)
    with pytest.raises(RuntimeError, match=r"blocked.*broker sessions live"):
        aethyme_graph.apply_refresh(tmp_path, "f" * 64)
    assert len(calls) == 1
    assert calls[0][1:4] == ["graph", "refresh", "plan"]


def test_rebuild_refuses_disabled_graph_authority_before_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_engine_pin(tmp_path)
    plan = _refresh_plan(authority="disabled")
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")
    calls: list[list[str]] = []

    def write_disabled_plan(args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        calls.append(args)
        assert stdout is not None
        json.dump(plan, stdout)
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_disabled_plan)
    with pytest.raises(RuntimeError, match="committed graph authority is not enabled"):
        aethyme_graph.apply_refresh(tmp_path, "f" * 64)
    assert len(calls) == 1


def test_rebuild_refuses_runtime_version_different_from_repository_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_engine_pin(tmp_path)
    plan = _refresh_plan(pinned="0.8.26", installed="0.4.2")
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")

    def write_plan(_args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        assert stdout is not None
        json.dump(plan, stdout)
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_plan)
    with pytest.raises(RuntimeError, match="Aethyme runtime does not match repository pin"):
        aethyme_graph.apply_refresh(tmp_path, "f" * 64)


def test_explore_smoke_requires_fresh_navigation_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")

    def write_answer(_args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        assert stdout is not None
        json.dump(
            {
                "status": "complete",
                "safe_to_use_as_navigation": True,
                "answer": [{"summary": "proxy/app.py"}],
                "observability": {"readiness": {"fresh_enough": True, "graph_freshness_status": "fresh"}},
            },
            stdout,
        )
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_answer)
    aethyme_graph.explore_smoke(tmp_path)


def test_explore_smoke_rejects_a_stale_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")

    def write_answer(_args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        assert stdout is not None
        json.dump(
            {
                "status": "complete",
                "safe_to_use_as_navigation": True,
                "answer": [{"summary": "proxy/app.py"}],
                "observability": {"readiness": {"fresh_enough": False, "graph_freshness_status": "stale"}},
            },
            stdout,
        )
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_answer)
    with pytest.raises(RuntimeError, match="freshness is unverified"):
        aethyme_graph.explore_smoke(tmp_path)


@pytest.mark.parametrize("safe_value", ["yes", 1, {"enabled": True}])
def test_explore_smoke_requires_boolean_navigation_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, safe_value: object
) -> None:
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "aethyme")

    def write_answer(_args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        del cwd
        assert stdout is not None
        json.dump(
            {
                "status": "complete",
                "safe_to_use_as_navigation": safe_value,
                "answer": [{"summary": "proxy/app.py"}],
                "observability": {"readiness": {"fresh_enough": True, "graph_freshness_status": "fresh"}},
            },
            stdout,
        )
        stdout.flush()

    monkeypatch.setattr(aethyme_graph, "_run", write_answer)
    with pytest.raises(RuntimeError, match="no answer-safe navigation evidence"):
        aethyme_graph.explore_smoke(tmp_path)
