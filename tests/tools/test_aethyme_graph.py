# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import aethyme_graph  # noqa: E402


def test_rebuild_restores_previous_graph_when_engine_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    graph = tmp_path / ".aethyme" / "graph"
    graph.mkdir(parents=True)
    (graph / "previous.bin").write_bytes(b"previous")
    monkeypatch.setattr(aethyme_graph, "_resolve_binary", lambda *_args: "tool")

    calls = 0
    index_args: list[str] = []

    def fail_engine(_args: list[str], *, cwd: Path, stdout: IO[str] | None = None) -> None:
        nonlocal calls
        del stdout
        calls += 1
        if calls == 1:
            index_args.extend(_args)
            generated = cwd / ".aethyme" / "graph"
            generated.mkdir(parents=True)
            (generated / "partial.bin").write_bytes(b"partial")
            return
        message = "engine failed"
        raise RuntimeError(message)

    monkeypatch.setattr(aethyme_graph, "_run", fail_engine)
    with pytest.raises(RuntimeError, match="engine failed"):
        aethyme_graph.rebuild(tmp_path)
    assert (graph / "previous.bin").read_bytes() == b"previous"
    assert not (graph / "partial.bin").exists()
    ignored = [index_args[index + 1] for index, arg in enumerate(index_args) if arg == "--extra-ignore"]
    assert ignored == list(aethyme_graph.EXTRA_IGNORE_DIRS)
    assert ".quality" in ignored
    assert "coverage" in ignored


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
