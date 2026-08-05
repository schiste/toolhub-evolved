# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001 - standalone maintenance script, not an importable package
"""Move one /v1/<family>/ route group out of backend/v1.py into its own blueprint.

v1.py accumulated 83 of the application's 87 routes across 23 unrelated
resource families, which is why an unrelated change from two people lands in
the same file. Splitting it by hand is error-prone at that size, so the move is
mechanical here: a family takes its routes plus exactly the helpers nothing
else reaches, and everything still shared is imported from backend.v1.

Run:  python tools/split_v1_family.py <family> [--dry-run]
Then: verify the url_map is unchanged before committing.
"""

import ast
import collections
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1 = ROOT / "proxy" / "backend" / "v1.py"


def _analyse(src: str) -> tuple[dict, dict, set]:
    """Return top-level functions, each route's family, and module-level constants."""
    tree = ast.parse(src)
    top = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    consts = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    consts |= {n.target.id for n in tree.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    family: dict[str, str] = {}
    for name, node in top.items():
        for dec in node.decorator_list:
            for sub in ast.walk(dec):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.startswith("/v1/"):
                    family.setdefault(name, sub.value.split("/")[2])
    return top, family, consts


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _external_references() -> set[str]:
    """Names that already-split v1_* modules reach as `v1.<name>`.

    Those modules are invisible to an analysis that reads only v1.py, so a
    helper they depend on would look unused by anything but the family being
    extracted — and moving it breaks them.
    """
    found: set[str] = set()
    for path in (ROOT / "proxy" / "backend").glob("v1_*.py"):
        found |= set(re.findall(r"\bv1\.(\w+)", path.read_text()))
    return found


def plan(src: str, want: str) -> tuple[set[str], set[str]]:
    """Return the definitions that move, and the names they still need from v1.py.

    A helper moves only when *every* reference to it moves with it. Walking
    outward from routes is not enough: v1.py also has helpers called from
    functions no route reaches, and taking one of those out leaves the caller
    with an undefined name.
    """
    top, family, consts = _analyse(src)
    tree = ast.parse(src)
    # Who references what, including from module level and non-route helpers.
    referrers: dict[str, set[str]] = collections.defaultdict(set)
    for name, node in top.items():
        for used in _names(node) & set(top):
            if used != name:
                referrers[used].add(name)
    module_level = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            module_level |= _names(node) & set(top)
    pinned = module_level | _external_references()
    moving = {r for r, fam in family.items() if fam == want}
    # Grow by fixpoint: pull in a helper only once nothing outside `moving`
    # still refers to it.
    changed = True
    while changed:
        changed = False
        candidates = set()
        for name in moving:
            candidates |= _names(top[name]) & set(top)
        for helper in candidates - moving:
            if helper in family or helper in pinned:
                continue
            if referrers[helper] <= moving:
                moving.add(helper)
                changed = True
    stays = (set(top) - moving) | consts
    needs: set[str] = set()
    for name in moving:
        needs |= _names(top[name]) & stays
    return moving, needs - {"v1_bp"}


def split(want: str, *, dry_run: bool = False) -> int:
    src = V1.read_text()
    lines = src.splitlines(keepends=True)
    top, _, _ = _analyse(src)
    moving, needs = plan(src, want)
    if not moving:
        sys.stderr.write(f"no routes found for /v1/{want}/\n")
        return 1
    blocks = sorted(
        (
            (top[n].decorator_list[0].lineno if top[n].decorator_list else top[n].lineno) - 1,
            top[n].end_lineno,
        )
        for n in moving
    )
    slug = want.replace("-", "_")
    moved = "".join("".join(lines[a:b]).rstrip() + "\n\n\n" for a, b in blocks)
    moved = moved.replace("@v1_bp.route", f"@v1_{slug}_bp.route")
    dropped = {i for a, b in blocks for i in range(a, b)}
    kept = "".join(ln for i, ln in enumerate(lines) if i not in dropped)
    imports = src[src.index("\n", src.index('"""', src.index('"""') + 3)) : src.index("v1_bp = Blueprint")].strip()
    module = ROOT / "proxy" / "backend" / f"v1_{slug}.py"
    # Reach shared helpers through the module rather than importing the names.
    # `from backend.v1 import _helper` binds a second reference, so a test that
    # patches backend.v1._helper stops affecting this module — which silently
    # turned a stubbed call back into a real one, and only showed up as an
    # unrelated assertion and a suite that took twelve times as long.
    for name in sorted(needs, key=len, reverse=True):
        moved = re.sub(rf"(?<![\w.]){re.escape(name)}\b", f"v1.{name}", moved)
    body = (
        f"# SPDX-License-Identifier: GPL-3.0-or-later\n"
        f'"""The /v1/{want}/* endpoints, split out of backend/v1.py.\n\n'
        f"URL paths are unchanged; only the Flask endpoint names move under their\n"
        f"own blueprint. Helpers still shared with other families are reached as\n"
        f"`v1.<name>` so there is exactly one binding for each and patching or\n"
        f"reloading backend.v1 keeps working.\n"
        f'"""\n\n{imports}\n\nfrom backend import v1\n\n'
        f'v1_{slug}_bp = Blueprint("v1_{slug}", __name__)\n\n\n{moved.rstrip()}\n'
    )
    print(f"/v1/{want}/: {len(moving)} defs, {sum(b - a for a, b in blocks)} lines -> {module.name}")
    print(f"  v1.py {len(lines)} -> {len(kept.splitlines())} lines; {len(needs)} shared names imported")
    if dry_run:
        return 0
    module.write_text(body)
    V1.write_text(kept)
    # --fixable, not --select: narrowing the rule set makes every noqa for a
    # disabled rule look unused, and RUF100 then deletes it. That quietly
    # stripped 55 `# noqa: S101` directives the first time.
    subprocess.run(["ruff", "check", str(module), "--fix", "--fixable", "F401,I001", "-q"], cwd=ROOT, check=False)
    subprocess.run(["ruff", "format", "-q", str(module), str(V1)], cwd=ROOT, check=False)
    # A name left behind on either side is the failure mode that matters, and
    # it otherwise shows up much later as an unrelated test error.
    undefined = subprocess.run(
        ["ruff", "check", str(module), str(V1), "--select", "F821", "--output-format", "concise"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if undefined:
        print("  UNDEFINED NAMES after the split — do not commit:")
        for line in undefined.splitlines()[:10]:
            print("   ", line)
        return 1
    print(f"  register v1_{slug}_bp in backend/__init__.py, then verify the url_map")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: split_v1_family.py <family> [--dry-run]")
    sys.exit(split(args[0], dry_run="--dry-run" in sys.argv))
