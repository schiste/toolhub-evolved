# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the production static build helper."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import build_dist  # noqa: E402


def test_build_versions_html_assets_and_js_imports(monkeypatch, tmp_path):
    src = tmp_path / "public_html"
    dist = tmp_path / "dist"
    tmp = tmp_path / "dist.tmp"
    (src / "styles").mkdir(parents=True)
    (src / "lib" / "core").mkdir(parents=True)
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
