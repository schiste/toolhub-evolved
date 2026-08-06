# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001 - standalone hook script, not an importable package
"""Fail when the checked-in release notes no longer describe what is being pushed.

generate_marketing_changelog.py only rewrites the notes when a changelog
provider is configured. Without one the pre-push hook prints "skipped" and
carries on, record_deployment.py reads whatever is checked in, and the stale
text goes straight into the public manifest. That happened for 34 commits
across three days: the site told visitors the newest deployment "adds an
expanded and collapsed bottom-center release-notice component", which had
shipped days earlier.

Nothing failed, because nothing was checking. This does.

Each notes file records the range it describes in a header comment:

    <!-- Source range: 828438f..6d5c835 (34 commits) -->

Commits after that end point mean the notes are behind. Commits that only
touch the notes themselves do not count — writing them is necessarily the last
thing that happens, so requiring the range to name a commit that does not exist
yet would make the check impossible to satisfy.

Run: python tools/check_changelog_freshness.py [--head REV]
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = (
    ROOT / "docs/CHANGELOG-USER.md",
    ROOT / "docs/CHANGELOG-TECHNICAL-MARKETING.md",
)
#: Commits touching only these are the act of updating the notes, not work the
#: notes should have described.
EXEMPT = {path.relative_to(ROOT).as_posix() for path in NOTES}
RANGE_RE = re.compile(r"<!--\s*Source range:\s*(?P<range>[^\s;]+)")
#: Enough undescribed commits to make the point without burying the message.
MAX_LISTED = 10


def git(*args: str) -> str:
    """Run one git command in the repository and return its stdout."""
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=15).stdout


def recorded_end(path: Path) -> str | None:
    """Return the revision a notes file claims to describe up to."""
    try:
        head = path.read_text(encoding="utf-8")[:2000]
    except OSError:
        return None
    match = RANGE_RE.search(head)
    if not match:
        return None
    value = match.group("range")
    # Accept "a..b" and a bare revision alike.
    return value.split("..")[-1].strip() or None


def undescribed(end: str, head: str) -> list[str]:
    """Return `end..head` commits that changed anything but the notes."""
    shas = git("rev-list", "--no-merges", f"{end}..{head}").split()
    out = []
    for sha in shas:
        touched = {line for line in git("show", "--name-only", "--format=", sha).split("\n") if line.strip()}
        if touched - EXEMPT:
            subject = git("show", "--no-patch", "--format=%s", sha).strip()
            out.append(f"{sha[:9]} {subject}")
    return out


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    head = args[args.index("--head") + 1] if "--head" in args else "HEAD"
    problems: list[str] = []
    for path in NOTES:
        name = path.relative_to(ROOT).as_posix()
        end = recorded_end(path)
        if end is None:
            problems.append(f"{name}: no '<!-- Source range: ... -->' header, so its freshness cannot be checked")
            continue
        try:
            git("rev-parse", "--verify", f"{end}^{{commit}}")
        except subprocess.CalledProcessError:
            problems.append(f"{name}: records range ending at {end}, which is not a commit in this repository")
            continue
        missing = undescribed(end, head)
        if missing:
            listed = "\n".join(f"      {line}" for line in missing[:MAX_LISTED])
            more = f"\n      ... and {len(missing) - MAX_LISTED} more" if len(missing) > MAX_LISTED else ""
            problems.append(f"{name}: {len(missing)} commit(s) since {end} are not described:\n{listed}{more}")
    if not problems:
        return 0
    sys.stderr.write("release notes are stale:\n")
    for problem in problems:
        sys.stderr.write(f"  - {problem}\n")
    sys.stderr.write(
        "\n  Update docs/CHANGELOG-USER.md and docs/CHANGELOG-TECHNICAL-MARKETING.md,\n"
        "  set their 'Source range' header to the range they now describe, and commit\n"
        "  both. With a changelog provider configured, 'npm run changelog:marketing'\n"
        "  drafts them for you.\n",
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
