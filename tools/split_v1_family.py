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


def plan(src: str, want: str) -> tuple[set[str], set[str]]:
    """Return the definitions that move, and the names they still need from v1.py."""
    top, family, consts = _analyse(src)
    owner: dict[str, set[str]] = collections.defaultdict(set)
    for route, fam in family.items():
        seen, stack = set(), [route]
        while stack:
            cur = stack.pop()
            if cur not in top:
                continue
            for callee in _names(top[cur]) & set(top):
                if callee not in seen and callee not in family:
                    seen.add(callee)
                    stack.append(callee)
        for helper in seen:
            owner[helper].add(fam)
    moving = {r for r, fam in family.items() if fam == want}
    moving |= {h for h, fams in owner.items() if fams == {want}}
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
    subprocess.run(["ruff", "check", str(module), "--select", "F401,I001", "--fix", "-q"], cwd=ROOT, check=False)
    subprocess.run(["ruff", "format", "-q", str(module)], cwd=ROOT, check=False)
    print(f"  register v1_{slug}_bp in backend/__init__.py, then verify the url_map")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: split_v1_family.py <family> [--dry-run]")
    sys.exit(split(args[0], dry_run="--dry-run" in sys.argv))
