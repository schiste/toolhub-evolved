# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the local source-analysis CLI wrapper."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import analyze_source  # noqa: E402


def test_cli_tree_reader_prunes_dependency_directories(tmp_path):
    dependency = tmp_path / ".venv" / "lib" / "python3.14" / "site-packages" / "boolean"
    dependency.mkdir(parents=True)
    (dependency / "boolean.py").write_text("See https://en.wikipedia.org/wiki/Absorption_law", encoding="utf-8")
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.js").write_text("const api = new mw.Api();", encoding="utf-8")

    files = analyze_source._read_tree([tmp_path])

    assert files == [{"path": "src/app.js", "content": "const api = new mw.Api();"}]


def test_cli_tree_reader_spends_a_short_budget_on_the_code_not_the_reading(monkeypatch, tmp_path):
    # One slot, and the file that sorts first alphabetically is the one that only
    # describes the tool. The budget has to go to the file the tool is made of.
    monkeypatch.setattr(analyze_source, "MAX_FILES", 1)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("Download from https://packages.example.org/tool", encoding="utf-8")
    source = tmp_path / "src"
    source.mkdir()
    (source / "client.py").write_text("requests.get('https://api.acme-data.org/v1/things')", encoding="utf-8")

    assert [row["path"] for row in analyze_source._read_tree([tmp_path])] == ["src/client.py"]


def test_cli_tree_reader_keeps_extensionless_dependency_manifests(tmp_path):
    (tmp_path / "go.mod").write_text("module example\nrequire github.com/gorilla/mux v1.8.1\n", encoding="utf-8")
    (tmp_path / "Gemfile").write_text('gem "rails"\n', encoding="utf-8")
    (tmp_path / "Pipfile").write_text("[packages]\nrequests='*'\n", encoding="utf-8")

    files = analyze_source._read_tree([tmp_path])
    paths = {row["path"] for row in files}

    assert {"Gemfile", "Pipfile", "go.mod"} <= paths


def test_cli_collects_deterministic_git_context(monkeypatch, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.js").write_text("const api = new mw.Api();", encoding="utf-8")
    outputs = {
        ("rev-parse", "--show-toplevel"): str(tmp_path),
        ("config", "--get", "remote.origin.url"): "git@github.com:example/tool.git",
        ("branch", "--show-current"): "main",
        ("rev-parse", "HEAD"): "abc123",
        ("log", "-1", "--format=%cI"): "2026-07-29T12:00:00+00:00",
        ("describe", "--tags", "--abbrev=0"): "v1.0.0",
        ("symbolic-ref", "refs/remotes/origin/HEAD", "--short"): "origin/main",
        ("rev-list", "--count", "HEAD"): "12",
        ("log", "--format=%ae", "--max-count=500"): "ada@example.org\nada@example.org\nbob@example.org",
        ("status", "--porcelain"): " M src/app.js",
    }

    monkeypatch.setattr(analyze_source, "_git_output", lambda _root, args: outputs.get(tuple(args)))

    context = analyze_source._local_git_context([tmp_path])

    assert context["repository"]["url"] == "https://github.com/example/tool.git"
    assert context["repository"]["defaultBranch"] == "main"
    assert context["repository"]["commitCount"] == 12
    assert context["repository"]["contributorCount"] == 2
    assert context["repository"]["dirty"] is True


def test_cli_merges_context_json(tmp_path, capsys):
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.js").write_text("const api = new mw.Api();", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(
        '{"repository":{"url":"https://example.org/tool"},"declared":{"oauthScopes":["basic"]}}', encoding="utf-8"
    )

    assert analyze_source.main([str(tmp_path), "--context-json", str(context), "--no-git-context"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["repositoryContext"]["repository"]["url"] == "https://example.org/tool"
    assert output["repositoryContext"]["declared"]["oauthScopes"] == ["basic"]


def test_cli_prints_json_for_valid_source(tmp_path, capsys):
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.js").write_text("const api = new mw.Api();", encoding="utf-8")

    assert analyze_source.main([str(tmp_path), "--tool-name", "sample-tool"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["toolName"] == "sample-tool"
    assert output["summary"]["filesAnalyzed"] == 1
    assert output["apis"][0]["value"] == "mediawiki-action-api"


def test_cli_reports_missing_paths_without_traceback(tmp_path, capsys):
    missing = tmp_path / "missing"

    try:
        analyze_source.main([str(missing)])
    except SystemExit as exc:
        assert exc.code == 2

    assert "path does not exist" in capsys.readouterr().err
