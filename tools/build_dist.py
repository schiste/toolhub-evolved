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

import shutil
import sys
from pathlib import Path

import rcssmin
import rjsmin

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "public_html"
DIST = ROOT / "dist"
TMP = ROOT / "dist.tmp"


def build() -> tuple[int, int]:
    """Mirror SRC into DIST, minifying .js/.css and copying everything else.

    Builds into a temp dir and swaps it in atomically, so an interrupted build
    never leaves a partial dist/ for the proxy to serve.
    """
    if TMP.exists():
        shutil.rmtree(TMP)
    raw = mini = 0
    for path in sorted(SRC.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(SRC)
        out = TMP / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if path.suffix == ".js":
            text = rjsmin.jsmin(data.decode("utf-8"))
            out.write_text(text, encoding="utf-8")
            raw += len(data)
            mini += len(text.encode("utf-8"))
        elif path.suffix == ".css":
            text = rcssmin.cssmin(data.decode("utf-8"))
            out.write_text(text, encoding="utf-8")
            raw += len(data)
            mini += len(text.encode("utf-8"))
        else:
            out.write_bytes(data)  # html, svg, etc. copied verbatim
    if DIST.exists():
        shutil.rmtree(DIST)
    TMP.rename(DIST)  # swap the freshly-built tree in
    return raw, mini


if __name__ == "__main__":
    raw_bytes, mini_bytes = build()
    pct = 0 if raw_bytes == 0 else round((raw_bytes - mini_bytes) * 100 / raw_bytes)
    sys.stdout.write(f"Built {DIST} — JS/CSS {raw_bytes} -> {mini_bytes} bytes ({pct}% smaller, pre-gzip)\n")
