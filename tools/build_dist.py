# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001 - standalone deploy script, not an importable package
"""Build a production `dist/` mirror of `public_html/` for serving.

The project is deliberately no-build and served raw in development, but the
Toolforge webservice has no Node toolchain. CSS is minified with pure-Python
rcssmin, while JS stays unminified because Python JS minifiers are not reliable
for this app's modern template-literal rendering. `proxy/app.py` serves `dist/`
when it exists and falls back to `public_html/` otherwise, so local dev is
unaffected unless a previous build is present.

Run from anywhere: `python tools/build_dist.py`.
"""

import gzip
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "public_html"
DIST = ROOT / "dist"
TMP = ROOT / "dist.tmp"
_HTML_ASSET_RE = re.compile(
    r'(?P<attr>\b(?:href|src)=)(?P<quote>["\'])(?P<url>/[^"\']+\.(?:css|js))(?P<query>\?[^"\']*)?(?P=quote)'
)
_JS_IMPORT_RE = re.compile(
    r'(?P<prefix>\bfrom\s*|import\s*\(\s*)(?P<quote>["\'])(?P<url>(?:\.{1,2}/)[^"\']+\.js)(?P<query>\?[^"\']*)?(?P=quote)'
)


# Only `from "./x.js"` / `export … from "./x.js"`, deliberately not `import()`.
# A dynamic import is a route chunk the router fetches on demand; preloading
# those would undo the code splitting.
_STATIC_IMPORT_RE = re.compile(r'\bfrom\s*(?P<quote>["\'])(?P<url>(?:\.{1,2}/)[^"\']+\.js)(?P=quote)')
# Entry points whose static graphs are preloaded. main.js is the app shell;
# home.js is the landing route, and without it the router cannot even request
# the view until it has loaded and run — measured at 1792ms into the page load,
# with the view's own imports adding two more round-trip waves after that.
# Other routes stay lazy: a visitor who lands on one pays for one chunk, where
# preloading every route would cost every visitor all of them.
_PRELOAD_ENTRIES = ("main.js", "views/home.js")
_PRELOAD_MARKER = '<link rel="modulepreload"'


def _module_graph(entry: Path) -> list[Path]:
    """Return every module reachable from `entry` through static imports.

    Breadth-first from the entry, so the emitted order roughly matches the
    order the browser would have discovered them in.
    """
    seen: set[Path] = set()
    order: list[Path] = []
    queue = [entry]
    while queue:
        path = queue.pop(0)
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        order.append(resolved)
        text = resolved.read_text(encoding="utf-8")
        queue.extend((resolved.parent / match.group("url")).resolve() for match in _STATIC_IMPORT_RE.finditer(text))
    return order


def preload_modules() -> list[str]:
    """Return root-relative URLs for every module the first paint needs."""
    urls: list[str] = []
    for entry in _PRELOAD_ENTRIES:
        for path in _module_graph(SRC / entry):
            url = "/" + path.relative_to(SRC).as_posix()
            if url not in urls:
                urls.append(url)
    return urls


def _preload_links(version: str, indent: str) -> str:
    """Render the modulepreload block for the whole first-paint module graph."""
    return "\n".join(
        f'{indent}<link rel="modulepreload" href="{_append_version(url, version)}" />' for url in preload_modules()
    )


def _inject_preloads(text: str, version: str) -> str:
    """Replace the hand-written modulepreload block with the derived graph.

    Nine of these were maintained by hand while the graph was 33 modules deep,
    so the browser discovered the rest a level at a time — six sequential waves
    of round trips before the first API call could start. Deriving the list from
    the imports keeps it complete and stops it rotting.
    """
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if _PRELOAD_MARKER in line]
    if not hits:
        return text
    first, last = hits[0], hits[-1]
    indent = lines[first][: len(lines[first]) - len(lines[first].lstrip())]
    return "\n".join([*lines[:first], _preload_links(version, indent), *lines[last + 1 :]]) + "\n"


def _source_fingerprint() -> str:
    """Return a local fingerprint for source changes not yet represented by git."""
    latest = max((path.stat().st_mtime_ns for path in SRC.rglob("*") if path.is_file()), default=0)
    return f"{latest:x}"


def _asset_version() -> str:
    """Return a stable build id for cache-busting deployed static assets."""
    if os.environ.get("TOOLHUB_ASSET_VERSION"):
        return os.environ["TOOLHUB_ASSET_VERSION"]
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if rev:
            dirty = subprocess.run(
                ["git", "status", "--porcelain", "--", "public_html"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            return f"{rev}-{_source_fingerprint()}" if dirty else rev
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return _source_fingerprint()


def _append_version(url: str, version: str) -> str:
    """Append a cache-busting query parameter unless this URL is already stamped."""
    if "v=" in url.split("?", 1)[-1].split("#", 1)[0]:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={version}"


def _version_html_assets(text: str, version: str) -> str:
    """Stamp first-party JS/CSS references emitted by index.html."""

    def repl(match: re.Match[str]) -> str:
        url = match.group("url") + (match.group("query") or "")
        return f"{match.group('attr')}{match.group('quote')}{_append_version(url, version)}{match.group('quote')}"

    return _HTML_ASSET_RE.sub(repl, text)


def _version_js_imports(text: str, version: str) -> str:
    """Stamp relative JS module imports so nested modules share the same build id."""

    def repl(match: re.Match[str]) -> str:
        url = match.group("url") + (match.group("query") or "")
        return f"{match.group('prefix')}{match.group('quote')}{_append_version(url, version)}{match.group('quote')}"

    return _JS_IMPORT_RE.sub(repl, text)


def _minify_js(text: str) -> str:
    """Return JavaScript unchanged.

    rjsmin rewrites leading spaces inside some template-literal interpolation
    strings, which can merge HTML class names at runtime. Keep JS source intact;
    the app's JS payload budget is enforced separately on public_html/.
    """
    return text


def _minify_css(text: str) -> str:
    import rcssmin

    return rcssmin.cssmin(text)


#: Suffixes worth storing a gzipped twin for. Everything here is text the
#: webservice would otherwise compress on every single request.
_PRECOMPRESS_SUFFIXES = {".js", ".css", ".html", ".json", ".svg", ".xml", ".txt", ".webmanifest"}
#: Below roughly one network packet, compression saves nothing. Matches the
#: request-time threshold in proxy/app.py so both paths agree on what is worth
#: compressing.
_PRECOMPRESS_MIN_BYTES = 1400
_PRECOMPRESS_LEVEL = 9
_STAGED_DATA = {Path("data/changelog.json"), Path("data/deployments.json")}


def _write_precompressed(out: Path) -> int:
    """Store a gzipped twin beside `out` when it is worth serving.

    The pod is capped at 500m of CPU and was spending 66% of its scheduling
    periods throttled; a cold page load fetches 33 ES modules and gzipped every
    one of them in-process. Doing it here means that work happens once per
    deploy instead of once per request, and it can afford level 9 where the
    request path could not.
    """
    if out.suffix not in _PRECOMPRESS_SUFFIXES:
        return 0
    raw = out.read_bytes()
    if len(raw) < _PRECOMPRESS_MIN_BYTES:
        return 0
    # mtime=0 keeps the output byte-identical for identical input, so an
    # unchanged asset does not churn its ETag on every deploy.
    packed = gzip.compress(raw, _PRECOMPRESS_LEVEL, mtime=0)
    # A "compressed" file that grew would just cost bytes and CPU to unpack.
    if len(packed) >= len(raw):
        return 0
    out.with_suffix(out.suffix + ".gz").write_bytes(packed)
    return len(packed)


def build(deployment_manifest: Path | None = None) -> tuple[int, int, int]:
    """Mirror SRC into DIST, preserving JS, minifying CSS, and copying everything else.

    Builds into a temp dir and swaps it in atomically, so an interrupted build
    never leaves a partial dist/ for the proxy to serve.
    """
    if TMP.exists():
        shutil.rmtree(TMP)
    version = _asset_version()
    raw = mini = packed = 0
    for path in sorted(SRC.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(SRC)
        if rel in _STAGED_DATA:
            continue
        out = TMP / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if path.suffix == ".js":
            text = _minify_js(_version_js_imports(data.decode("utf-8"), version))
            out.write_text(text, encoding="utf-8")
            raw += len(data)
            mini += len(text.encode("utf-8"))
        elif path.suffix == ".css":
            text = _minify_css(data.decode("utf-8"))
            out.write_text(text, encoding="utf-8")
            raw += len(data)
            mini += len(text.encode("utf-8"))
        elif path.suffix == ".html":
            html = _version_html_assets(data.decode("utf-8"), version)
            if rel.name == "index.html":
                html = _inject_preloads(html, version)
            out.write_text(html, encoding="utf-8")
        else:
            out.write_bytes(data)
        packed += _write_precompressed(out)
    if deployment_manifest is not None:
        release_out = TMP / "data" / "deployments.json"
        release_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(deployment_manifest, release_out)
        packed += _write_precompressed(release_out)
    if DIST.exists():
        shutil.rmtree(DIST)
    TMP.rename(DIST)  # swap the freshly-built tree in
    return raw, mini, packed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-manifest", type=Path)
    args = parser.parse_args()
    raw_bytes, mini_bytes, packed_bytes = build(args.deployment_manifest)
    pct = 0 if raw_bytes == 0 else round((raw_bytes - mini_bytes) * 100 / raw_bytes)
    sys.stdout.write(
        f"Built {DIST} — JS preserved, CSS minified; JS/CSS {raw_bytes} -> {mini_bytes} bytes "
        f"({pct}% smaller, pre-gzip); {packed_bytes} bytes of gzipped twins stored\n"
    )
