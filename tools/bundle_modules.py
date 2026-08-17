# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001 - build-time helper for tools/build_dist.py, not an importable package
"""Concatenate the app's ES modules into a handful of bundles.

Why this exists
---------------
The app ships raw ES modules, one HTTP request each. That is fine against a
server where a request is nearly free; it is not fine here. The webservice pod
is capped at 500m CPU, and a cold landing page asked for 39 modules: measured
in production, they completed in a steady drip of roughly three per 100ms —
the CFS scheduler period — taking 1.8s to deliver 122 KB that the network
could have carried in a fraction of that. proxy/uwsgi.ini reached the same
conclusion from the server side: "the fix for a CPU cap is to need less CPU,
not to add concurrency in front of it." Fewer requests is the only lever left.

Why concatenation is enough
---------------------------
This is deliberately not a general bundler. It works because the app's module
graph is uniform in ways a survey confirmed: every import is
`import { … } from "./relative.js"`, there are no namespace imports, no default
exports, no `export *`, no `import.meta`, and no import cycles. With no cycles
a topological order exists, and with no colliding top-level names the modules
can share one scope without renaming anything. Those last two are invariants,
not observations, so `plan()` re-checks them on every build and fails loudly
rather than emitting a bundle that is subtly wrong.

The deploy host has no Node (see tools/deploy.sh), which is why this is Python
rather than esbuild — the same reason CSS is minified with rcssmin.

How the split works
-------------------
Every module lands in exactly one bundle, because a module that appeared twice
would have two copies of its top-level state — two `evolvedSummaryCache`s, two
locale registries — and the app would fail in ways that are miserable to debug.
`plan()` asserts that invariant.

* ``core`` is the static graph of the shell plus the landing route: exactly the
  set that was already being modulepreloaded, so the landing payload keeps its
  current byte count and simply arrives in one response instead of 39.
* ``common`` holds modules that more than one lazy route needs. Keeping them
  out of core is what stops the landing page paying for routes nobody visited.
* one bundle per lazy route, holding only that route's private modules.

Cross-bundle references become real module imports (`import { t } from
"/bundle/app.js"`), so the browser's module map keeps one instance of each.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: `import { a, b } from "./x.js"`. `[^}]*` spans newlines, which covers the
#: handful of modules that wrap a long import list across several lines.
_IMPORT = re.compile(r'import\s*\{(?P<names>[^}]*)\}\s*from\s*(?P<q>["\'])(?P<url>\.{1,2}/[^"\']+\.js)(?P=q)\s*;?')
#: `export { a } from "./x.js"` — an import and an export at once. Must be
#: matched before _IMPORT and _EXPORT_LIST, both of which would half-match it.
_REEXPORT = re.compile(r'export\s*\{(?P<names>[^}]*)\}\s*from\s*(?P<q>["\'])(?P<url>\.{1,2}/[^"\']+\.js)(?P=q)\s*;?')
#: `export { a };` on its own line.
_EXPORT_LIST = re.compile(r"^[ \t]*export\s*\{(?P<names>[^}]*)\}\s*;?[ \t]*$", re.M)
#: The `export ` prefix on a top-level declaration, at column zero only.
_EXPORT_DECL = re.compile(r"^export\s+", re.M)
#: `import("./views/x.js")` — a lazy route boundary, rewritten to its bundle.
_DYNAMIC = re.compile(r'import\(\s*(?P<q>["\'])(?P<url>\.{1,2}/[^"\']+\.js)(?P=q)\s*\)')
#: Any top-level declaration, used for the collision check.
_TOP_LEVEL_DECL = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)", re.M)
#: An exported top-level declaration: `export function f`, `export const x`, …
_EXPORT_NAMED = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)", re.M)
#: `new URL("../workers/x.js", import.meta.url)` — a Worker entry. A worker is a
#: separate realm that loads its own graph, so those modules cannot be replaced
#: by a bundle reference; they have to stay on disk as files.
_WORKER_URL = re.compile(r'new\s+URL\(\s*(?P<q>["\'])(?P<url>\.{1,2}/[^"\']+\.js)(?P=q)')
#: A bare relative-module string that is not itself an import. Only one thing in
#: this app produces them — views/router.js passes the specifier alongside the
#: loader so a failed route load can be retried under a fresh URL — but they are
#: still specifiers, and a bundled module no longer exists at that path.
_LITERAL_SPEC = re.compile(r'(?P<q>["\'])(?P<url>\.{1,2}/[^"\']+\.js)(?P=q)')


def _specs(raw: str) -> list[str]:
    """Split an import/export brace list into its specifiers, aliases intact.

    An alias has to survive: `import { lifecycleMeta as baseLifecycleMeta }`
    means the exporting bundle must export `lifecycleMeta` while the importing
    body refers to `baseLifecycleMeta`. Collapsing the two would export a name
    that is not declared anywhere.
    """
    specs = []
    for part in raw.split(","):
        # Collapse the newlines and padding of a wrapped import list, so
        # `a\n    as\n    b` and `a as b` normalise to the same specifier.
        tokens = part.split()
        if not tokens:
            continue
        specs.append(f"{tokens[0]} as {tokens[-1]}" if len(tokens) == 3 and tokens[1] == "as" else tokens[0])
    return specs


def _exported_name(spec: str) -> str:
    """The name the *source* module declares — the left half of `a as b`."""
    return spec.split(" as ")[0].strip()


def _local_name(spec: str) -> str:
    """The name the *importing* body uses — the right half of `a as b`."""
    return spec.split(" as ")[-1].strip()


def exported_names(module: Path) -> set[str]:
    """Every name `module` exports.

    Needed for dynamic-import targets. A static importer names what it wants, so
    the bundle can export exactly that; a dynamic importer gets the whole
    namespace object and reaches into it by property access
    (`import("./x.js").then((m) => m.viewHome())`), which no regex can enumerate
    from the call site. So the target's full surface has to leave its bundle.
    """
    text = module.read_text(encoding="utf-8")
    names = set(_EXPORT_NAMED.findall(text))
    for match in (*_EXPORT_LIST.finditer(text), *_REEXPORT.finditer(text)):
        names.update(_local_name(spec) for spec in _specs(match.group("names")))
    return names


def _resolve(module: Path, url: str) -> Path:
    return (module.parent / url).resolve()


def static_deps(module: Path) -> list[Path]:
    """Modules `module` pulls in at load time, including through re-exports."""
    text = module.read_text(encoding="utf-8")
    return [_resolve(module, m.group("url")) for m in (*_IMPORT.finditer(text), *_REEXPORT.finditer(text))]


def dynamic_deps(module: Path) -> list[Path]:
    """Lazy route boundaries `module` can reach."""
    return [_resolve(module, m.group("url")) for m in _DYNAMIC.finditer(module.read_text(encoding="utf-8"))]


def static_graph(entry: Path) -> set[Path]:
    """Every module reachable from `entry` without crossing a lazy boundary."""
    seen: set[Path] = set()
    queue = [entry.resolve()]
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        queue.extend(static_deps(path))
    return seen


@dataclass
class Bundle:
    """One emitted file: the modules it holds, in load order."""

    name: str
    modules: list[Path] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"/bundle/{self.name}.js"


@dataclass
class Plan:
    bundles: list[Bundle]
    #: module -> the bundle that owns it, for rewriting cross-bundle references.
    owner: dict[Path, Bundle]
    #: modules a Worker loads. They are bundled for the main realm *and* kept as
    #: files, because the worker fetches them itself and a worker's copy of a
    #: module is a separate instance by design, not an accident.
    standalone: set[Path] = field(default_factory=set)
    #: the source root, for turning a module path back into a served URL.
    src: Path = Path()


class BundleError(RuntimeError):
    """A build-stopping violation of an invariant the concatenation relies on."""


def _topological(modules: set[Path]) -> list[Path]:
    """Order `modules` so every module follows the ones it imports.

    Only edges inside the set matter: a dependency in another bundle arrives as
    a real import at the top of the file, already evaluated by the time this
    body runs.
    """
    ordered: list[Path] = []
    done: set[Path] = set()
    visiting: set[Path] = set()

    def visit(path: Path) -> None:
        if path in done:
            return
        if path in visiting:
            # plan() rejects cycles before we get here; this keeps a future
            # cycle from becoming infinite recursion instead of an error.
            raise BundleError(f"import cycle through {path}")
        visiting.add(path)
        for dep in sorted(static_deps(path)):
            if dep in modules:
                visit(dep)
        visiting.discard(path)
        done.add(path)
        ordered.append(path)

    for path in sorted(modules):
        visit(path)
    return ordered


def _check_no_cycles(modules: set[Path]) -> None:
    colour: dict[Path, int] = {}

    def visit(path: Path, trail: list[Path]) -> None:
        colour[path] = 1
        for dep in static_deps(path):
            if dep not in modules:
                continue
            if colour.get(dep) == 1:
                loop = [p.name for p in trail[trail.index(dep) :]] + [dep.name]
                raise BundleError("import cycle: " + " -> ".join(loop))
            if colour.get(dep, 0) == 0:
                visit(dep, [*trail, dep])
        colour[path] = 2

    for path in sorted(modules):
        if colour.get(path, 0) == 0:
            visit(path, [path])


def _check_no_collisions(bundles: list[Bundle], src: Path) -> None:
    """Reject two modules in the *same* bundle declaring the same top-level name.

    Concatenation puts a bundle's modules in one scope, so a repeated name would
    let one module silently overwrite another's state. Renaming automatically
    would mean rewriting identifiers, which is where a regex-based bundler stops
    being trustworthy — so this fails the build and asks for a rename in source.

    The check is deliberately per bundle rather than app-wide: two lazy routes
    that never share a file are free to both call a local helper `dateLabel`,
    and demanding app-wide unique private names would be a tax on every future
    contributor for no correctness gain.
    """
    clashes: list[str] = []
    for bundle in bundles:
        owners: dict[str, Path] = {}
        for path in bundle.modules:
            for match in _TOP_LEVEL_DECL.finditer(path.read_text(encoding="utf-8")):
                name = match.group(1)
                first = owners.get(name)
                if first is not None:
                    clashes.append(
                        f"  [{bundle.name}] {name}: "
                        f"{first.relative_to(src).as_posix()} and {path.relative_to(src).as_posix()}"
                    )
                else:
                    owners[name] = path
    if clashes:
        raise BundleError(
            "top-level names must be unique within a bundle; rename one of each pair:\n" + "\n".join(clashes)
        )


#: Module syntax this bundler does not rewrite. Each of these needs a per-module
#: namespace or binding that concatenation into one scope cannot express, and
#: every one of them is absent from the app today — so the honest move is to fail
#: the build the day someone introduces one, rather than emit a bundle that
#: parses and then behaves differently from the source.
_UNSUPPORTED = (
    (re.compile(r"^export\s*\*", re.M), "`export *` — a bundle has no per-module namespace to forward"),
    (re.compile(r"^export\s+default\b", re.M), "`export default` — use a named export"),
    (re.compile(r"^import\s+(?:\*\s+as\s+[\w$]+|[\w$]+)\s*(?:,|from)", re.M), "a default or namespace import"),
    (re.compile(r'^import\s*["\']', re.M), "a bare side-effect import"),
)


def _check_supported_syntax(modules: set[Path], src: Path) -> None:
    found: list[str] = []
    for module in sorted(modules):
        text = module.read_text(encoding="utf-8")
        found.extend(
            f"  {module.relative_to(src).as_posix()}: {why}" for pattern, why in _UNSUPPORTED if pattern.search(text)
        )
    if found:
        raise BundleError("tools/bundle_modules.py cannot bundle this syntax:\n" + "\n".join(found))


def _slug(module: Path, src: Path) -> str:
    return module.relative_to(src).as_posix().removesuffix(".js").replace("/", "-")


def plan(src: Path, core_entries: tuple[str, ...]) -> Plan:
    """Partition every reachable module into bundles.

    `core_entries` is the shell plus the landing route — the set already being
    modulepreloaded. Everything else is reached through a lazy `import()`.
    """
    src = src.resolve()
    core_modules: set[Path] = set()
    for entry in core_entries:
        core_modules |= static_graph(src / entry)

    # Walk lazy boundaries transitively: a route can lazily load another.
    lazy_entries: set[Path] = set()
    frontier = list(core_modules)
    seen_entries: set[Path] = set()
    while frontier:
        module = frontier.pop()
        for target in dynamic_deps(module):
            if target in core_modules or target in seen_entries or not target.is_file():
                continue
            seen_entries.add(target)
            lazy_entries.add(target)
            frontier.extend(static_graph(target))

    private = {entry: static_graph(entry) - core_modules for entry in lazy_entries}
    shared_count: dict[Path, int] = {}
    for graph in private.values():
        for module in graph:
            shared_count[module] = shared_count.get(module, 0) + 1
    common_modules = {module for module, count in shared_count.items() if count > 1}

    everything = core_modules | common_modules | {m for g in private.values() for m in g}
    _check_supported_syntax(everything, src)
    _check_no_cycles(everything)

    bundles = [Bundle("app", _topological(core_modules))]
    if common_modules:
        bundles.append(Bundle("common", _topological(common_modules)))
    for entry in sorted(lazy_entries):
        members = private[entry] - common_modules
        if members:
            bundles.append(Bundle(f"route-{_slug(entry, src)}", _topological(members)))

    owner: dict[Path, Bundle] = {}
    for bundle in bundles:
        for module in bundle.modules:
            if module in owner:
                raise BundleError(f"{module} would be emitted into two bundles")
            owner[module] = bundle
    missing = everything - set(owner)
    if missing:
        raise BundleError(f"modules assigned to no bundle: {sorted(p.name for p in missing)}")
    _check_no_collisions(bundles, src)

    standalone: set[Path] = set()
    for module in everything:
        for match in _WORKER_URL.finditer(module.read_text(encoding="utf-8")):
            target = _resolve(module, match.group("url"))
            if target.is_file():
                standalone |= static_graph(target)
    return Plan(bundles=bundles, owner=owner, standalone=standalone, src=src)


def render(bundle: Bundle, plan_: Plan, stamp) -> str:
    """Emit one bundle's source.

    Each module contributes its body with the module-level syntax removed:
    imports satisfied inside this bundle vanish (the name is already in scope),
    imports crossing a bundle boundary are collected into one real import at the
    top, and `export` keywords are stripped in favour of a single export list at
    the bottom naming everything other bundles ask for.

    `stamp` turns a bundle URL into its cache-busting form.
    """
    #: names this bundle must pull in from another, keyed by that bundle's url
    foreign: dict[str, set[str]] = {}
    #: names another bundle imports from this one
    exported: set[str] = set()
    bodies: list[str] = []

    members = set(bundle.modules)

    for module in bundle.modules:
        text = module.read_text(encoding="utf-8")

        def take(match: re.Match[str], *, reexport: bool) -> str:
            target = _resolve(module, match.group("url"))
            specs = _specs(match.group("names"))
            if reexport:
                # The names stay live in the shared scope under their local
                # spelling; whether they leave this bundle is decided below.
                exported.update(_local_name(spec) for spec in specs)
            if target not in members:
                home = plan_.owner.get(target)
                if home is None:
                    # Not bundled (should not happen): leave the import alone so
                    # the browser still resolves it rather than losing the name.
                    return match.group(0)
                foreign.setdefault(home.url, set()).update(specs)
            return ""

        text = _REEXPORT.sub(lambda m: take(m, reexport=True), text)
        text = _IMPORT.sub(lambda m: take(m, reexport=False), text)
        text = _EXPORT_LIST.sub(lambda m: "", text)
        text = _EXPORT_DECL.sub("", text)
        text = _DYNAMIC.sub(
            lambda m: (
                f'import("{stamp(home.url)}")'
                if (home := plan_.owner.get(_resolve(module, m.group("url")))) is not None
                else m.group(0)
            ),
            text,
        )
        # A Worker URL is resolved against `import.meta.url`, which inside a
        # bundle is the bundle's own URL — so a path relative to the module that
        # wrote it now points somewhere else entirely. Root-absolute resolves the
        # same against any base, and still lets the caller copy `?v=` across.
        text = _WORKER_URL.sub(
            lambda m: m.group(0).replace(
                m.group("url"), "/" + _resolve(module, m.group("url")).relative_to(plan_.src).as_posix()
            ),
            text,
        )
        # Whatever relative specifiers are left are the ones held as data, and
        # the only consumer appends its own query string. Deliberately unstamped
        # so `${specifier}?retry=…` stays a well-formed URL — and a retry wants
        # to miss the cache anyway, which is the whole reason it exists. A
        # literal pointing at something unbundled (a Worker entry) is left alone.
        text = _LITERAL_SPEC.sub(
            lambda m: (
                f'"{home.url}"'
                if (home := plan_.owner.get(_resolve(module, m.group("url")))) is not None
                else m.group(0)
            ),
            text,
        )
        bodies.append(f"// {module.name}\n{text.strip()}\n")

    # Anything another bundle imports from a module of ours has to leave here.
    for other in plan_.bundles:
        for module in other.modules:
            source = module.read_text(encoding="utf-8")
            if other is not bundle:
                for match in (*_IMPORT.finditer(source), *_REEXPORT.finditer(source)):
                    if plan_.owner.get(_resolve(module, match.group("url"))) is bundle:
                        # What leaves here is what our modules declare, not what
                        # the importer chose to call it.
                        exported.update(_exported_name(spec) for spec in _specs(match.group("names")))
            # Dynamic imports are checked from every bundle including this one:
            # a route lazily loaded from the shell can live in the shell's own
            # bundle, and `import("/bundle/app.js")` from inside app.js still
            # reads the export list rather than the surrounding scope.
            for match in _DYNAMIC.finditer(source):
                target = _resolve(module, match.group("url"))
                if plan_.owner.get(target) is bundle:
                    exported.update(exported_names(target))

    head = "".join(
        f'import {{ {", ".join(sorted(names))} }} from "{stamp(url)}";\n' for url, names in sorted(foreign.items())
    )
    tail = f"export {{ {', '.join(sorted(exported))} }};\n" if exported else ""
    banner = "// SPDX-License-Identifier: GPL-3.0-or-later\n// Generated by tools/bundle_modules.py — do not edit.\n"
    return banner + head + "\n" + "\n".join(bodies) + "\n" + tail
