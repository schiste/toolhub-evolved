# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the pure-Python ES module bundler.

These cover the invariants concatenation depends on rather than its output
formatting: a module in two bundles would carry two copies of its state, and an
export list naming something the shared scope does not declare is a load-time
SyntaxError that no amount of `node --check` on the source would have caught.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import bundle_modules  # noqa: E402


def _write(src: Path, rel: str, text: str) -> None:
    path = src / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _render_all(src: Path) -> dict[str, str]:
    plan = bundle_modules.plan(src, ("main.js",))
    return {b.name: bundle_modules.render(b, plan, lambda url: url + "?v=1") for b in plan.bundles}


def test_every_module_lands_in_exactly_one_bundle(tmp_path):
    """Two copies of a module means two copies of its top-level state.

    A second `evolvedSummaryCache` or locale registry fails in ways that are
    miserable to debug, so this is asserted rather than assumed.
    """
    src = tmp_path / "public_html"
    _write(src, "main.js", 'export const boot = () => [import("./a.js"), import("./b.js")];\n')
    # Both lazy routes need shared.js, so it belongs to neither of them.
    _write(src, "a.js", 'import { s } from "./shared.js";\nexport const a = () => s;\n')
    _write(src, "b.js", 'import { s } from "./shared.js";\nexport const b = () => s;\n')
    _write(src, "shared.js", "export const s = 1;\n")

    plan = bundle_modules.plan(src, ("main.js",))

    placements = [module for bundle in plan.bundles for module in bundle.modules]
    assert len(placements) == len(set(placements))
    assert plan.owner[(src / "shared.js").resolve()].name == "common"
    assert plan.owner[(src / "a.js").resolve()] is not plan.owner[(src / "b.js").resolve()]


def test_a_renamed_import_exports_the_declared_name(tmp_path):
    """`import { x as y }` means the source bundle exports `x`, not `y`.

    Exporting the importer's chosen spelling names something the exporting
    bundle never declared, which the browser rejects when it links the module.
    """
    src = tmp_path / "public_html"
    _write(src, "main.js", 'import { meta as baseMeta } from "./shared.js";\nexport const boot = () => baseMeta;\n')
    _write(src, "shared.js", 'export const meta = 1;\nexport const other = () => import("./lazy.js");\n')
    _write(src, "lazy.js", 'import { meta } from "./shared.js";\nexport const l = () => meta;\n')

    rendered = _render_all(src)

    # shared.js sits in the entry bundle with main.js, so the alias is resolved
    # inside one scope and nothing has to cross a boundary for it.
    assert "as baseMeta" not in rendered["app"].split("\n\n")[0]
    assert "const baseMeta" not in rendered["app"]
    # The lazy route does cross, and imports the declared name.
    assert 'import { meta } from "/bundle/app.js?v=1";' in rendered["route-lazy"]
    assert "export { " in rendered["app"] and "meta" in rendered["app"].rsplit("export {", 1)[1]


def test_a_dynamic_import_target_exports_its_whole_surface(tmp_path):
    """A dynamic importer reaches into the namespace by property access.

    `import("./x.js").then((m) => m.viewHome())` names nothing the bundler can
    see at the call site, so everything the target declares has to leave its
    bundle — including when the target ends up in the caller's own bundle and
    the rewritten `import()` reads that bundle's export list.
    """
    src = tmp_path / "public_html"
    _write(src, "main.js", 'export const boot = () => import("./home.js").then((m) => m.viewHome());\n')
    _write(src, "home.js", "export const viewHome = () => 1;\nexport const helper = () => 2;\n")

    plan = bundle_modules.plan(src, ("main.js", "home.js"))
    app = bundle_modules.render(plan.bundles[0], plan, lambda url: url + "?v=1")

    assert plan.owner[(src / "home.js").resolve()].name == "app"
    assert 'import("/bundle/app.js?v=1")' in app
    exports = app.rsplit("export {", 1)[1]
    assert "viewHome" in exports
    assert "helper" in exports


def test_a_retry_specifier_held_as_data_follows_its_module(tmp_path):
    """views/router.js passes the specifier alongside the loader.

    A failed route load is retried under a fresh URL built from that string. It
    is not an import the regexes rewrite, but it is still a specifier, and the
    path it names no longer exists once the module is bundled.
    """
    src = tmp_path / "public_html"
    _write(
        src,
        "main.js",
        'const load = (spec, loader) => loader().catch(() => import(`${spec}?retry=1`));\n'
        'export const boot = () => load("./lazy.js", () => import("./lazy.js"));\n',
    )
    _write(src, "lazy.js", "export const l = 1;\n")

    app = _render_all(src)["app"]

    # Unstamped, so `${spec}?retry=…` stays a well-formed URL — and a retry
    # wants to miss the cache, which is the entire reason it exists.
    assert 'load("/bundle/route-lazy.js", () => import("/bundle/route-lazy.js?v=1"))' in app


def test_an_import_cycle_is_reported_with_its_path(tmp_path):
    """No cycles is what makes a topological order exist at all."""
    src = tmp_path / "public_html"
    _write(src, "main.js", 'import { a } from "./a.js";\nexport const boot = () => a;\n')
    _write(src, "a.js", 'import { b } from "./b.js";\nexport const a = () => b;\n')
    _write(src, "b.js", 'import { a } from "./a.js";\nexport const b = () => a;\n')

    with pytest.raises(bundle_modules.BundleError, match="import cycle"):
        bundle_modules.plan(src, ("main.js",))


def test_a_module_follows_everything_it_imports(tmp_path):
    """Concatenation order is evaluation order.

    A `const` read at module scope before its declaration is a TDZ error, so
    dependencies have to appear above the modules that use them.
    """
    src = tmp_path / "public_html"
    _write(src, "main.js", 'import { mid } from "./mid.js";\nexport const boot = () => mid;\n')
    _write(src, "mid.js", 'import { leaf } from "./leaf.js";\nexport const mid = leaf + 1;\n')
    _write(src, "leaf.js", "export const leaf = 1;\n")

    app = _render_all(src)["app"]

    assert app.index("const leaf = 1") < app.index("const mid = leaf + 1") < app.index("const boot")


def _big(name: str, size: int = 9000) -> str:
    """A module large enough to be worth its own request."""
    return f"export const {name} = 1;\n" + f"// {'x' * 60}\n" * (size // 61)


def test_shared_code_is_grouped_by_the_routes_that_want_it(tmp_path):
    """A route should pay for the code it runs, not for the pool.

    `heavy.js` is wanted by two of the three routes. Pooling it into one shared
    bundle would put it on the wire for the third as well, which is how the
    lazy payload of an average route grew to several times the size of the
    route itself.
    """
    src = tmp_path / "public_html"
    _write(src, "main.js", 'export const boot = () => [import("./a.js"), import("./b.js"), import("./c.js")];\n')
    _write(src, "a.js", 'import { heavy } from "./heavy.js";\nexport const a = () => heavy;\n')
    _write(src, "b.js", 'import { heavy } from "./heavy.js";\nexport const b = () => heavy;\n')
    _write(src, "c.js", "export const c = 1;\n")
    _write(src, "heavy.js", _big("heavy"))

    plan = bundle_modules.plan(src, ("main.js",))
    home = plan.owner[(src / "heavy.js").resolve()]

    assert home.name == "shared-heavy"
    rendered = _render_all(src)
    assert home.url in rendered["route-a"]
    assert home.url in rendered["route-b"]
    assert home.url not in rendered["route-c"]


def test_two_shared_groups_do_not_pool_into_one_bundle(tmp_path):
    """Sharing with a different route is not the same as sharing.

    Both modules below are wanted by exactly two routes, but not by the same
    two. One bundle holding both would make /a fetch what only /c runs.
    """
    src = tmp_path / "public_html"
    _write(src, "main.js", 'export const boot = () => [import("./a.js"), import("./b.js"), import("./c.js")];\n')
    _write(src, "a.js", 'import { ab } from "./ab.js";\nexport const a = () => ab;\n')
    _write(src, "b.js", 'import { ab } from "./ab.js";\nimport { bc } from "./bc.js";\nexport const b = () => [ab, bc];\n')
    _write(src, "c.js", 'import { bc } from "./bc.js";\nexport const c = () => bc;\n')
    _write(src, "ab.js", _big("ab"))
    _write(src, "bc.js", _big("bc"))

    plan = bundle_modules.plan(src, ("main.js",))
    ab = plan.owner[(src / "ab.js").resolve()]
    bc = plan.owner[(src / "bc.js").resolve()]

    assert ab is not bc
    rendered = _render_all(src)
    assert bc.url not in rendered["route-a"]
    assert ab.url not in rendered["route-c"]


def test_a_small_shared_group_rides_along_in_common(tmp_path):
    """Below a few kilobytes the round trip costs more than the bytes."""
    src = tmp_path / "public_html"
    _write(src, "main.js", 'export const boot = () => [import("./a.js"), import("./b.js")];\n')
    _write(src, "a.js", 'import { tiny } from "./tiny.js";\nexport const a = () => tiny;\n')
    _write(src, "b.js", 'import { tiny } from "./tiny.js";\nexport const b = () => tiny;\n')
    _write(src, "tiny.js", "export const tiny = 1;\n")

    plan = bundle_modules.plan(src, ("main.js",))

    assert plan.owner[(src / "tiny.js").resolve()].name == "common"
