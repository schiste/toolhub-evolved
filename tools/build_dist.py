# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001 - standalone deploy script, not an importable package
"""Build a production `dist/` mirror of `public_html/` for serving.

The project is deliberately no-build and served raw in development, but the
Toolforge webservice has no Node toolchain. CSS is minified with pure-Python
rcssmin, while JS stays unminified because Python JS minifiers are not reliable
for this app's modern template-literal rendering. JS *is* bundled — see
tools/bundle_modules.py for why 39 requests was the landing page's dominant
cost. `proxy/app.py` serves `dist/` when it exists and falls back to
`public_html/` otherwise, so local dev is unaffected unless a previous build is
present.

Run from anywhere: `python tools/build_dist.py`.
"""

import gzip
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from . import bundle_modules
except ImportError:
    # Run as a script rather than imported as tools.build_dist, so `tools` is
    # not a package here and the sibling has to be found on the path. Both
    # spellings must reach the *same* module object, or `except BundleError`
    # would be catching a different class than the one raised.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import bundle_modules  # type: ignore[no-redef]

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
#: The one `<script type="module">` that boots the app. In dist it has to name
#: the bundle holding main.js instead, or the browser would load the shell
#: twice — once unbundled, once inside the bundle — with two copies of every
#: module-level cache.
_ENTRY_SCRIPT_RE = re.compile(r'(?P<prefix><script\b[^>]*\btype="module"[^>]*\bsrc=")(?P<url>/[^"?]+\.js)(?P<suffix>")')


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


def _preload_links(version: str, indent: str, urls: list[str] | None = None) -> str:
    """Render the modulepreload block for the whole first-paint module graph."""
    return "\n".join(
        f'{indent}<link rel="modulepreload" href="{_append_version(url, version)}" />'
        for url in (preload_modules() if urls is None else urls)
    )


def _inject_preloads(text: str, version: str, urls: list[str] | None = None) -> str:
    """Replace the hand-written modulepreload block with the derived graph.

    Nine of these were maintained by hand while the graph was 33 modules deep,
    so the browser discovered the rest a level at a time — six sequential waves
    of round trips before the first API call could start. Deriving the list from
    the imports keeps it complete and stops it rotting.

    Once the graph is bundled there is a single entry to preload, and `urls`
    carries it: the preload block and the module `src` must name the same URL or
    the browser fetches the bundle twice.
    """
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if _PRELOAD_MARKER in line]
    if not hits:
        return text
    first, last = hits[0], hits[-1]
    indent = lines[first][: len(lines[first]) - len(lines[first].lstrip())]
    return "\n".join([*lines[:first], _preload_links(version, indent, urls), *lines[last + 1 :]]) + "\n"


#: Any module specifier left in a built file: a relative import, or the absolute
#: `/bundle/…` URL a rewritten one becomes.
_ANY_SPEC_RE = re.compile(r'(?P<quote>["\'])(?P<url>(?:\.{1,2}/|/bundle/)[^"\']+\.js)(?:\?[^"\']*)?(?P=quote)')


def _check_specifiers_resolve(root: Path) -> None:
    """Fail the build if any emitted module points at a file that is not there.

    Bundling deletes the standalone copy of every module it absorbs, so a file
    the bundler does not know about — a Worker entry, say — can be left holding
    an import of something that no longer exists. That is invisible until a user
    hits the one route that loads it, which is far too late to find out.
    """
    missing: list[str] = []
    for path in sorted(root.rglob("*.js")):
        for match in _ANY_SPEC_RE.finditer(path.read_text(encoding="utf-8")):
            url = match.group("url")
            target = (root / url.lstrip("/")) if url.startswith("/") else (path.parent / url)
            if not target.resolve().is_file():
                missing.append(f"  {path.relative_to(root).as_posix()} -> {url}")
    if missing:
        raise SystemExit("build_dist: emitted modules import files that were not built:\n" + "\n".join(missing))


def _point_entry_at_bundle(text: str, bundle_url: str) -> str:
    """Repoint the boot `<script type="module">` at its bundle."""
    return _ENTRY_SCRIPT_RE.sub(lambda m: f"{m.group('prefix')}{bundle_url}{m.group('suffix')}", text, count=1)


def _source_fingerprint() -> str:
    """Return a local fingerprint for source changes not yet represented by git."""
    latest = max((path.stat().st_mtime_ns for path in SRC.rglob("*") if path.is_file()), default=0)
    return f"{latest:x}"


#: One `<link rel="preload" ... data-deferred-style />` from the shell's global
#: stylesheet block. main.js turns each into a real stylesheet once the module
#: graph resolves (see activateDeferredStyles).
_DEFERRED_STYLE_RE = re.compile(
    r'^(?P<indent>[ \t]*)<link rel="preload" href="(?P<url>/styles/[^"]+\.css)" as="style" data-deferred-style />[ \t]*\n',
    re.MULTILINE,
)
#: The no-JS fallback for the same block.
_STYLE_NOSCRIPT_RE = re.compile(
    r'^(?P<indent>[ \t]*)<noscript>[ \t]*\n'
    r'(?P<links>(?:[ \t]*<link rel="stylesheet" href="/styles/[^"]+\.css" />[ \t]*\n)+)'
    r'[ \t]*</noscript>[ \t]*\n',
    re.MULTILINE,
)
#: Where the merged global stylesheet lands.
_GLOBAL_STYLE_URL = "/styles/app.css"


def global_stylesheets(index_html: str) -> list[str]:
    """The shell's global stylesheets, in cascade order.

    Read out of index.html rather than listed here, so adding a seventh layer
    to the design system is a one-line edit to the shell and the build follows.
    """
    return [match.group("url") for match in _DEFERRED_STYLE_RE.finditer(index_html)]


def _merge_global_styles(text: str, urls: list[str]) -> str:
    """Point the shell at one merged stylesheet instead of the whole layering.

    Six files that always load together are six responses and six separately
    compressed streams; concatenated they share a compression dictionary and
    arrive in one. The layers stay separate in `public_html/` because that is
    where they are read and edited — the same no-build-in-development split the
    JS bundler makes.
    """
    if not urls:
        return text

    matches = list(_DEFERRED_STYLE_RE.finditer(text))
    indent = matches[0].group("indent")
    merged = indent + '<link rel="preload" href="' + _GLOBAL_STYLE_URL + '" as="style" data-deferred-style />\n'
    seen = 0

    def one(_match: re.Match[str]) -> str:
        nonlocal seen
        seen += 1
        return merged if seen == 1 else ""

    text = _DEFERRED_STYLE_RE.sub(one, text)

    noscript = _STYLE_NOSCRIPT_RE.search(text)
    if noscript is None:
        raise SystemExit("index.html: global stylesheets have a preload block but no <noscript> fallback")
    pad = noscript.group("indent")
    fallback = (
        pad
        + "<noscript>\n"
        + pad
        + '\t<link rel="stylesheet" href="'
        + _GLOBAL_STYLE_URL
        + '" />\n'
        + pad
        + "</noscript>\n"
    )
    return text[: noscript.start()] + fallback + text[noscript.end() :]


#: The shell's route hint table, as a JSON island the build can rewrite without
#: parsing the surrounding script.
_ROUTE_HINTS_RE = re.compile(
    r'(?P<open>[ \t]*<script type="application/json" id="route-hints">\n)'
    r"(?P<body>.*?)"
    r"(?P<close>[ \t]*</script>\n)",
    re.DOTALL,
)


def _fill_route_hint_bundles(text: str, plan_: bundle_modules.Plan, app_bundle_url: str, version: str) -> str:
    """Resolve each hint's view module into the bundles that serve it.

    The shell knows the route before app.js has parsed, but only the build knows
    which bundle a view ended up in — that depends on how the routes divide the
    shared code between them, and it changes whenever they do. So the shell names
    a source module and the build answers with urls, rather than the shell
    hardcoding a bundle name that quietly stops existing.

    A hint naming a module that is gone is a build failure, not a silent skip: an
    unresolved hint still looks like a working page, just a slower one, which is
    the kind of regression nobody notices for months.
    """
    island = _ROUTE_HINTS_RE.search(text)
    if island is None:
        return text

    hints = json.loads(island.group("body"))
    for path, hint in sorted(hints.items()):
        module = hint.pop("module", None)
        if module is None:
            continue
        target = (plan_.src / module).resolve()
        if not target.exists():
            raise SystemExit(f"index.html: route hint {path} names a module that does not exist: {module}")
        # Everything the view pulls in statically, minus the entry bundle the
        # shell already preloads for every route.
        serving = {
            plan_.owner[dependency].url
            for dependency in bundle_modules.static_graph(target)
            if dependency in plan_.owner
        }
        hint["bundles"] = sorted(_append_version(url, version) for url in serving if url != app_bundle_url)
        # A hinted route may also own a stylesheet. It stays unversioned on
        # purpose: views/router.js requests the bare url, and a preload for a
        # different url is a second fetch rather than a head start.
        sheet = hint.get("css")
        if sheet and not (plan_.src / sheet.lstrip("/")).exists():
            raise SystemExit(f"index.html: route hint {path} names a stylesheet that does not exist: {sheet}")

    indent = island.group("open")[: len(island.group("open")) - len(island.group("open").lstrip("\t"))]
    body = "\n".join(indent + "\t" + line for line in json.dumps(hints, indent="\t", sort_keys=True).splitlines())
    return text[: island.start("body")] + body + "\n" + text[island.end("body") :]


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

    Gzipping in the request path is not only CPU per hit: it forces the whole
    body through memory instead of streaming off disk, which measured 899ms
    against 483ms for the same 8.2 KB document in production. Doing it here
    means the work happens once per deploy rather than once per request, and it
    can afford level 9 where the request path could not.
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


def build(deployment_manifest: Path | None = None) -> tuple[int, int, int, list[str]]:
    """Mirror SRC into DIST, bundling JS, minifying CSS, and copying everything else.

    Builds into a temp dir and swaps it in atomically, so an interrupted build
    never leaves a partial dist/ for the proxy to serve.

    Returns the raw/emitted/gzipped byte counts and the unreachable JS that was
    left out of the tree.
    """
    if TMP.exists():
        shutil.rmtree(TMP)
    version = _asset_version()
    plan = bundle_modules.plan(SRC, _PRELOAD_ENTRIES)
    app_bundle = plan.bundles[0]
    global_styles = global_stylesheets((SRC / "index.html").read_text(encoding="utf-8"))
    #: minified global layers, keyed by url, concatenated in cascade order below
    merged_css: dict[str, str] = {}
    dropped: list[str] = []
    raw = mini = packed = 0
    for path in sorted(SRC.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(SRC)
        if rel in _STAGED_DATA:
            continue
        # A bundled module is already inside its bundle. Shipping the standalone
        # copy too would only invite something to import it and get a second
        # instance with its own module-level state.
        if path.suffix == ".js" and path.resolve() not in plan.standalone:
            if path.resolve() in plan.owner:
                raw += path.stat().st_size  # its bytes reappear in a bundle below
                continue
            # Reachable from neither the entry graph, a lazy route, nor a
            # Worker. Shipping it would ship a file whose own imports were
            # bundled away — a 404 waiting for whoever first loads it.
            dropped.append(rel.as_posix())
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
            raw += len(data)
            if f"/{rel.as_posix()}" in global_styles:
                # Held back for the merged sheet below; shipping it as well
                # would serve the same rules twice under two urls.
                merged_css[f"/{rel.as_posix()}"] = text
                continue
            out.write_text(text, encoding="utf-8")
            mini += len(text.encode("utf-8"))
        elif path.suffix == ".html":
            html = data.decode("utf-8")
            if rel.name == "index.html":
                html = _point_entry_at_bundle(html, app_bundle.url)
                html = _merge_global_styles(html, global_styles)
                html = _fill_route_hint_bundles(html, plan, app_bundle.url, version)
            html = _version_html_assets(html, version)
            if rel.name == "index.html":
                html = _inject_preloads(html, version, [app_bundle.url])
            out.write_text(html, encoding="utf-8")
        else:
            out.write_bytes(data)
        packed += _write_precompressed(out)
    missing = [url for url in global_styles if url not in merged_css]
    if missing:
        raise SystemExit(f"index.html names global stylesheets that do not exist: {missing}")
    if merged_css:
        out = TMP / _GLOBAL_STYLE_URL.lstrip("/")
        out.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(merged_css[url] for url in global_styles)
        out.write_text(text, encoding="utf-8")
        mini += len(text.encode("utf-8"))
        packed += _write_precompressed(out)
    for bundle in plan.bundles:
        out = TMP / "bundle" / f"{bundle.name}.js"
        out.parent.mkdir(parents=True, exist_ok=True)
        text = _minify_js(bundle_modules.render(bundle, plan, lambda url: _append_version(url, version)))
        out.write_text(text, encoding="utf-8")
        mini += len(text.encode("utf-8"))
        packed += _write_precompressed(out)
    if deployment_manifest is not None:
        release_out = TMP / "data" / "deployments.json"
        release_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(deployment_manifest, release_out)
        packed += _write_precompressed(release_out)
    _check_specifiers_resolve(TMP)
    if DIST.exists():
        shutil.rmtree(DIST)
    TMP.rename(DIST)  # swap the freshly-built tree in
    return raw, mini, packed, dropped


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-manifest", type=Path)
    args = parser.parse_args()
    raw_bytes, mini_bytes, packed_bytes, unreachable = build(args.deployment_manifest)
    pct = 0 if raw_bytes == 0 else round((raw_bytes - mini_bytes) * 100 / raw_bytes)
    sys.stdout.write(
        f"Built {DIST} — JS bundled, CSS minified; JS/CSS {raw_bytes} -> {mini_bytes} bytes "
        f"({pct}% smaller, pre-gzip); {packed_bytes} bytes of gzipped twins stored\n"
    )
    if unreachable:
        sys.stdout.write("Left out (reachable from no entry, worker or route): " + ", ".join(unreachable) + "\n")
