# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the production static build helper."""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import build_dist  # noqa: E402


def test_asset_version_uses_git_rev_for_clean_static_tree(monkeypatch):
    def fake_run(args, **_kwargs):
        if args[:3] == ["git", "rev-parse", "--short=12"]:
            return SimpleNamespace(stdout="abc123\n")
        if args[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.delenv("TOOLHUB_ASSET_VERSION", raising=False)
    monkeypatch.setattr(build_dist.subprocess, "run", fake_run)

    assert build_dist._asset_version() == "abc123"


def test_asset_version_changes_for_uncommitted_static_tree(monkeypatch, tmp_path):
    src = tmp_path / "public_html"
    src.mkdir()
    (src / "main.js").write_text("export const ok = true;\n", encoding="utf-8")

    def fake_run(args, **_kwargs):
        if args[:3] == ["git", "rev-parse", "--short=12"]:
            return SimpleNamespace(stdout="abc123\n")
        if args[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(stdout=" M public_html/main.js\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.delenv("TOOLHUB_ASSET_VERSION", raising=False)
    monkeypatch.setattr(build_dist, "SRC", src)
    monkeypatch.setattr(build_dist.subprocess, "run", fake_run)

    assert build_dist._asset_version().startswith("abc123-")


def test_build_versions_html_assets_and_js_imports(monkeypatch, tmp_path):
    src = tmp_path / "public_html"
    dist = tmp_path / "dist"
    tmp = tmp_path / "dist.tmp"
    (src / "styles").mkdir(parents=True)
    (src / "lib" / "core").mkdir(parents=True)
    (src / "lib" / "workers").mkdir(parents=True)
    (src / "views").mkdir(parents=True)
    (src / "index.html").write_text(
        """<!doctype html>
<link rel="stylesheet" href="/styles/base.css">
<link rel="modulepreload" href="/main.js">
<script type="module" src="/main.js"></script>
""",
        encoding="utf-8",
    )
    (src / "main.js").write_text(
        'import { $ } from "./lib/core/dom.js";\nimport("./views/graph.js").then((m) => m.viewGraph());\n',
        encoding="utf-8",
    )
    (src / "styles" / "base.css").write_text("body { color: black; }\n", encoding="utf-8")
    (src / "lib" / "core" / "dom.js").write_text("export const $ = () => null;\n", encoding="utf-8")
    (src / "lib" / "workers" / "graph-layout-worker.js").write_text("self.onmessage = () => {};\n", encoding="utf-8")
    (src / "views" / "graph.js").write_text("export function viewGraph() {}\n", encoding="utf-8")

    monkeypatch.setattr(build_dist, "SRC", src)
    monkeypatch.setattr(build_dist, "DIST", dist)
    monkeypatch.setattr(build_dist, "TMP", tmp)
    monkeypatch.setattr(build_dist, "_asset_version", lambda: "abc123")
    monkeypatch.setattr(build_dist, "_minify_js", lambda text: text)
    monkeypatch.setattr(build_dist, "_minify_css", lambda text: text)

    build_dist.build()

    html = (dist / "index.html").read_text(encoding="utf-8")
    assert 'href="/styles/base.css?v=abc123"' in html
    assert 'href="/main.js?v=abc123"' in html
    assert 'src="/main.js?v=abc123"' in html

    main = (dist / "main.js").read_text(encoding="utf-8")
    assert 'from "./lib/core/dom.js?v=abc123"' in main
    assert 'import("./views/graph.js?v=abc123")' in main
    assert (dist / "lib" / "workers" / "graph-layout-worker.js").is_file()


def test_js_build_preserves_template_literal_class_spacing():
    source = 'const html = `<a class="${base}${current ? " is-active" : ""}" href="/x">x</a>`;\n'
    assert build_dist._minify_js(source) == source
