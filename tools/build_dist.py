# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001 - standalone deploy script, not an importable package
"""Build a minified `dist/` mirror of `public_html/` for production serving.

The project is deliberately no-build and served raw in development, but the
Toolforge webservice has no Node toolchain — so we minify with the pure-Python
rjsmin/rcssmin (conservative comment + whitespace stripping, no name mangling,
string/regex/template-literal safe). `proxy/app.py` serves `dist/` when it
exists and falls back to `public_html/` otherwise, so local dev is unaffected.

Run from anywhere: `python tools/build_dist.py`.
"""

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
            return rev
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    latest = max((path.stat().st_mtime_ns for path in SRC.rglob("*") if path.is_file()), default=0)
    return hex(latest)[2:]


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
    import rjsmin

    return rjsmin.jsmin(text)


def _minify_css(text: str) -> str:
    import rcssmin

    return rcssmin.cssmin(text)


def build() -> tuple[int, int]:
    """Mirror SRC into DIST, minifying .js/.css and copying everything else.

    Builds into a temp dir and swaps it in atomically, so an interrupted build
    never leaves a partial dist/ for the proxy to serve.
    """
    if TMP.exists():
        shutil.rmtree(TMP)
    version = _asset_version()
    raw = mini = 0
    for path in sorted(SRC.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(SRC)
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
            out.write_text(_version_html_assets(data.decode("utf-8"), version), encoding="utf-8")
        else:
            out.write_bytes(data)
    if DIST.exists():
        shutil.rmtree(DIST)
    TMP.rename(DIST)  # swap the freshly-built tree in
    return raw, mini


if __name__ == "__main__":
    raw_bytes, mini_bytes = build()
    pct = 0 if raw_bytes == 0 else round((raw_bytes - mini_bytes) * 100 / raw_bytes)
    sys.stdout.write(f"Built {DIST} — JS/CSS {raw_bytes} -> {mini_bytes} bytes ({pct}% smaller, pre-gzip)\n")
