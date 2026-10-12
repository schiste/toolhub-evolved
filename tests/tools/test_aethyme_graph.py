# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO

import pytest

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
    assert calls[2][1:3] == ["explore", "--repo"]
    assert all("execute" not in args for args in calls)


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
    with pytest.raises(RuntimeError, match="stale graph"):
        aethyme_graph.explore_smoke(tmp_path)
