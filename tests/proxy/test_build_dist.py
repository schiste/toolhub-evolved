# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the production static build helper."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import build_dist, bundle_modules  # noqa: E402


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


def _fixture_app(tmp_path):
    """A miniature of the real app: shell, landing route, lazy route, worker."""
    src = tmp_path / "public_html"
    (src / "styles").mkdir(parents=True)
    (src / "lib" / "core").mkdir(parents=True)
    (src / "lib" / "workers").mkdir(parents=True)
    (src / "views").mkdir(parents=True)
    (src / "data").mkdir(parents=True)
    (src / "index.html").write_text(
        """<!doctype html>
<link rel="stylesheet" href="/styles/base.css">
<link rel="modulepreload" href="/main.js">
<link rel="modulepreload" href="/stale.js">
<script type="module" src="/main.js"></script>
""",
        encoding="utf-8",
    )
    (src / "main.js").write_text(
        'import { $ } from "./lib/core/dom.js";\n'
        'import { viewHome } from "./views/home.js";\n'
        'export const boot = () => import("./views/graph.js").then((m) => m.viewGraph($, viewHome));\n',
        encoding="utf-8",
    )
    (src / "styles" / "base.css").write_text("body { color: black; }\n", encoding="utf-8")
    (src / "lib" / "core" / "dom.js").write_text("export const $ = () => null;\n", encoding="utf-8")
    (src / "lib" / "core" / "layout.js").write_text("export const settle = () => 1;\n", encoding="utf-8")
    (src / "lib" / "workers" / "graph-layout-worker.js").write_text(
        'import { settle } from "../core/layout.js";\nself.onmessage = () => settle();\n', encoding="utf-8"
    )
    (src / "views" / "home.js").write_text(
        'import { $ } from "../lib/core/dom.js";\nexport const viewHome = () => $();\n', encoding="utf-8"
    )
    (src / "views" / "graph.js").write_text(
        'export function viewGraph() {\n\treturn new URL("../lib/workers/graph-layout-worker.js", import.meta.url);\n}\n',
        encoding="utf-8",
    )
    (src / "data" / "changelog.json").write_text('{"retired": true}\n', encoding="utf-8")
    (src / "data" / "deployments.json").write_text('{"stale": true}\n', encoding="utf-8")
    return src


def _use_fixture(monkeypatch, tmp_path, src):
    monkeypatch.setattr(build_dist, "SRC", src)
    monkeypatch.setattr(build_dist, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_dist, "TMP", tmp_path / "dist.tmp")
    monkeypatch.setattr(build_dist, "_asset_version", lambda: "abc123")
    monkeypatch.setattr(build_dist, "_minify_js", lambda text: text)
    monkeypatch.setattr(build_dist, "_minify_css", lambda text: text)
    return tmp_path / "dist"


def test_build_versions_html_assets_and_stages_data(monkeypatch, tmp_path):
    src = _fixture_app(tmp_path)
    dist = _use_fixture(monkeypatch, tmp_path, src)
    staged_manifest = tmp_path / "staged-deployments.json"
    staged_manifest.write_text('{"deployments": [{"id": "current"}]}\n', encoding="utf-8")

    build_dist.build(staged_manifest)

    html = (dist / "index.html").read_text(encoding="utf-8")
    assert 'href="/styles/base.css?v=abc123"' in html
    assert not (dist / "data" / "changelog.json").exists()
    assert (
        json.loads((dist / "data" / "deployments.json").read_text(encoding="utf-8"))["deployments"][0]["id"]
        == "current"
    )


def test_build_points_the_page_at_one_bundle(monkeypatch, tmp_path):
    """The whole first-paint graph arrives as a single response.

    39 modules were being fetched for a cold landing page, and against a pod
    capped at 500m CPU they completed at roughly three per 100ms scheduling
    period — 1.8s to deliver 122 KB. The bytes were never the problem; the
    request count was.
    """
    src = _fixture_app(tmp_path)
    dist = _use_fixture(monkeypatch, tmp_path, src)

    build_dist.build()
    html = (dist / "index.html").read_text(encoding="utf-8")

    assert 'src="/bundle/app.js?v=abc123"' in html
    # The preload and the script must name the same URL, or it is fetched twice.
    assert '<link rel="modulepreload" href="/bundle/app.js?v=abc123" />' in html
    assert html.count("modulepreload") == 1
    # The hand-written block is replaced, not appended to.
    assert "/stale.js" not in html
    # The absorbed modules are gone: a second copy would carry its own state.
    assert not (dist / "main.js").exists()
    assert not (dist / "views" / "home.js").exists()

    app = (dist / "bundle" / "app.js").read_text(encoding="utf-8")
    assert "const $ = () => null;" in app
    assert "const viewHome = () => $();" in app
    # A lazy route stays lazy — bundling it into the shell would undo the split.
    assert "function viewGraph" not in app
    assert 'import("/bundle/route-views-graph.js?v=abc123")' in app


def test_build_keeps_worker_modules_on_disk(monkeypatch, tmp_path):
    """A Worker is a separate realm that fetches its own graph.

    Its modules cannot be replaced by a bundle reference, and its copy being a
    second instance is the design rather than an accident. The `new URL(…)` that
    locates it is resolved against `import.meta.url`, which inside a bundle is
    the bundle's URL — so the path has to stop being relative to the module that
    wrote it.
    """
    src = _fixture_app(tmp_path)
    dist = _use_fixture(monkeypatch, tmp_path, src)

    build_dist.build()

    assert (dist / "lib" / "workers" / "graph-layout-worker.js").is_file()
    assert (dist / "lib" / "core" / "layout.js").is_file()
    route = (dist / "bundle" / "route-views-graph.js").read_text(encoding="utf-8")
    assert 'new URL("/lib/workers/graph-layout-worker.js", import.meta.url)' in route


#: Gzipped bytes the landing page may cost. The unbundled app shipped 122 KB
#: across 39 responses; the same modules concatenated and gzipped as one stream
#: measured 94 KB. This is the wire-side budget — tools/js-budget.mjs bounds
#: total source on disk, which is a different question.
_LANDING_GZIP_LIMIT = 120_000


def test_landing_page_costs_one_request_within_budget(monkeypatch, tmp_path):
    """Measured against the real app, not a fixture.

    The bundling exists for one number: how much the browser has to ask for
    before the landing page can render. A fixture cannot regress that.
    """
    monkeypatch.setattr(build_dist, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_dist, "TMP", tmp_path / "dist.tmp")
    monkeypatch.setattr(build_dist, "_asset_version", lambda: "abc123")
    monkeypatch.setattr(build_dist, "_minify_css", lambda text: text)

    build_dist.build()
    dist = tmp_path / "dist"
    html = (dist / "index.html").read_text(encoding="utf-8")

    assert html.count("modulepreload") == 1
    assert 'src="/bundle/app.js?v=abc123"' in html
    packed = (dist / "bundle" / "app.js.gz").stat().st_size
    assert packed <= _LANDING_GZIP_LIMIT, f"landing bundle is {packed} gzipped bytes"


def test_js_build_preserves_template_literal_class_spacing():
    source = 'const html = `<a class="${base}${current ? " is-active" : ""}" href="/x">x</a>`;\n'
    assert build_dist._minify_js(source) == source


def test_build_rejects_a_module_it_cannot_bundle(monkeypatch, tmp_path):
    """Unsupported syntax stops the build rather than being mangled quietly.

    `export *` forwards a namespace that concatenation into one shared scope has
    no way to represent. Stripping the `export` keyword the way every other
    declaration is handled would leave `* from "…"`, so this has to be a loud
    failure the day someone writes one.
    """
    src = _fixture_app(tmp_path)
    (src / "views" / "home.js").write_text('export * from "../lib/core/dom.js";\n', encoding="utf-8")
    _use_fixture(monkeypatch, tmp_path, src)

    with pytest.raises(bundle_modules.BundleError, match=r"export \*"):
        build_dist.build()


def test_build_rejects_a_name_declared_twice_in_one_bundle(monkeypatch, tmp_path):
    """Two modules sharing a bundle share a scope, so they cannot share a name.

    Renaming automatically would mean rewriting identifiers, which is where a
    regex-driven bundler stops being trustworthy — so the build asks for the
    rename in source instead. The check is per bundle on purpose: two routes
    that never meet are free to both call a local helper the same thing.
    """
    src = _fixture_app(tmp_path)
    (src / "views" / "home.js").write_text(
        'import { $ } from "../lib/core/dom.js";\n'
        "const settle = () => $();\n"
        "export const viewHome = () => settle();\n",
        encoding="utf-8",
    )
    # Same name, but in a lazy route's private module: a different scope, fine.
    _use_fixture(monkeypatch, tmp_path, src)
    build_dist.build()

    # Now put the clash inside one bundle.
    (src / "main.js").write_text(
        'import { $ } from "./lib/core/dom.js";\n'
        'import { viewHome } from "./views/home.js";\n'
        "const settle = () => $();\n"
        "export const boot = () => settle() && viewHome();\n",
        encoding="utf-8",
    )
    with pytest.raises(bundle_modules.BundleError, match="settle"):
        build_dist.build()


def test_build_rejects_an_emitted_import_that_points_nowhere(monkeypatch, tmp_path):
    """Bundling deletes the standalone copy of everything it absorbs.

    A file the bundler does not rewrite — a Worker's own module, say — can be
    left importing something that no longer exists on disk. That is invisible
    until a user hits the one route that loads it, so the build checks instead.
    """
    src = _fixture_app(tmp_path)
    (src / "lib" / "workers" / "graph-layout-worker.js").write_text(
        'import { gone } from "../core/missing.js";\nself.onmessage = () => gone();\n', encoding="utf-8"
    )
    _use_fixture(monkeypatch, tmp_path, src)

    with pytest.raises(SystemExit, match="missing.js"):
        build_dist.build()
