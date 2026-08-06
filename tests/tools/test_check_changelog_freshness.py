# SPDX-License-Identifier: GPL-3.0-or-later
"""The release-notes freshness gate."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/check_changelog_freshness.py"


def git(repo: Path, *args: str) -> str:
    """Run git in a scratch repository."""
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=15
    ).stdout.strip()


def commit(repo: Path, path: str, body: str, subject: str) -> str:
    """Write one file and commit it."""
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


def notes(end: str) -> str:
    """Render a notes file claiming to describe up to `end`."""
    return f"<!-- Source range: aaaaaaa..{end} -->\n\n# Notes\n\n- Something shipped.\n"


def run(repo: Path) -> subprocess.CompletedProcess:
    """Run the checker against a scratch repository."""
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True, timeout=30, check=False
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A scratch repository with the checker pointed at it."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.org")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.org")
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "app.py", "print('one')\n", "feat: first")
    # The checker resolves paths from its own location, so give it a tree there.
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return tmp_path


def check(repo: Path) -> tuple[int, str]:
    """Import the checker with ROOT rebound to the scratch repository."""
    import check_changelog_freshness as mod

    mod.ROOT = repo
    mod.NOTES = (repo / "docs/CHANGELOG-USER.md", repo / "docs/CHANGELOG-TECHNICAL-MARKETING.md")
    mod.EXEMPT = {p.relative_to(repo).as_posix() for p in mod.NOTES}
    import io
    import contextlib

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = mod.main([])
    return code, err.getvalue()


def write_notes(repo: Path, end: str, subject: str = "docs: update release notes") -> str:
    """Commit both notes files describing up to `end`."""
    for name in ("CHANGELOG-USER.md", "CHANGELOG-TECHNICAL-MARKETING.md"):
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / name).write_text(notes(end), encoding="utf-8")
    git(repo, "add", "docs")
    git(repo, "commit", "-q", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


def test_passes_when_only_the_notes_commit_follows_the_recorded_range(repo):
    """Writing the notes is necessarily the last thing that happens.

    Requiring the recorded range to name a commit that does not exist yet would
    make the gate impossible to satisfy, so a commit touching only the notes is
    not something the notes had to describe.
    """
    head = git(repo, "rev-parse", "HEAD")
    write_notes(repo, head[:7])

    code, err = check(repo)

    assert code == 0, err


def test_fails_when_real_work_shipped_after_the_recorded_range(repo):
    """The case that went unnoticed for 34 commits."""
    head = git(repo, "rev-parse", "HEAD")
    write_notes(repo, head[:7])
    commit(repo, "app.py", "print('two')\n", "feat: something users can see")

    code, err = check(repo)

    assert code == 1
    assert "feat: something users can see" in err
    assert "CHANGELOG-USER.md" in err


def test_fails_when_the_header_is_missing(repo):
    """A notes file with no recorded range cannot be checked, so it does not pass."""
    (repo / "docs").mkdir(exist_ok=True)
    for name in ("CHANGELOG-USER.md", "CHANGELOG-TECHNICAL-MARKETING.md"):
        (repo / "docs" / name).write_text("# Notes\n\n- No header here.\n", encoding="utf-8")
    git(repo, "add", "docs")
    git(repo, "commit", "-q", "-m", "docs: notes without a range")

    code, err = check(repo)

    assert code == 1
    assert "Source range" in err


def test_fails_when_the_recorded_range_is_not_a_commit(repo):
    """A rewritten or invented revision must not silently pass."""
    write_notes(repo, "deadbee")

    code, err = check(repo)

    assert code == 1
    assert "not a commit" in err
