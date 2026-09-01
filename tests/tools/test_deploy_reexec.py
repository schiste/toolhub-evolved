# SPDX-License-Identifier: GPL-3.0-or-later
"""The rollback target a failed deploy prints must survive the script's re-exec.

tools/deploy.sh pulls, and if the pull moved HEAD it re-execs the freshly pulled
copy of itself so the rest of the deploy runs the reviewed script rather than the
one that was on disk when the operator typed the command. That re-exec is also
the moment the pre-deploy SHA can be lost: the second process starts over from
the top, and `git rev-parse HEAD` now answers with the commit that was just
pulled. A smoke failure would then tell the operator to restore the very commit
that is breaking production, which docs/RUNBOOK.md promises it will not do.

The prologue is exercised here for real -- the copy under test is the shipped
file, truncated after the re-exec block and told to print what it decided --
with a stub `git` whose `pull` actually moves HEAD, because that is the only
case in which the two processes disagree.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "tools" / "deploy.sh"
BEFORE_SHA = "1111111111111111111111111111111111111111"
AFTER_SHA = "2222222222222222222222222222222222222222"


def _prologue(tmp_path: Path) -> Path:
    """The shipped script cut off after the re-exec, reporting its decision."""
    source = DEPLOY.read_text()
    marker = 'deploy_short="'
    assert marker in source, "deploy.sh prologue no longer ends where this test cuts it"
    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    script = tools / "deploy.sh"
    body = source[: source.index(marker)]
    script.write_text(f'{body}echo "ROLLBACK_TARGET=$deploy_head_before"\necho "DEPLOYED=$deploy_head_after"\n')
    return script


def _stub_git(tmp_path: Path) -> Path:
    """A `git` whose `pull` moves HEAD, like the pull a deploy actually does."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    head = tmp_path / "head"
    head.write_text(BEFORE_SHA)
    stub = bin_dir / "git"
    stub.write_text(
        # Match the subcommand, never the whole argument string: the repository
        # path is in there too, and a tmp directory named after this test would
        # otherwise make every `rev-parse` look like a `pull`.
        "#!/bin/sh\n"
        f'head_file="{head}"\n'
        '[ "$1" = "-C" ] && shift 2\n'
        'case "$1" in\n'
        f'  pull) printf %s "{AFTER_SHA}" > "$head_file" ;;\n'
        '  rev-parse) cat "$head_file" ;;\n'
        "esac\n"
    )
    stub.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path) -> dict[str, str]:
    script = _prologue(tmp_path)
    env = {"PATH": f"{_stub_git(tmp_path)}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env, timeout=60, check=True)
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line and line[0].isupper())


def test_a_pull_that_moves_head_still_reports_the_pre_deploy_commit(tmp_path: Path) -> None:
    reported = _run(tmp_path)

    assert reported["DEPLOYED"] == AFTER_SHA
    assert reported["ROLLBACK_TARGET"] == BEFORE_SHA, "the re-exec lost the pre-deploy SHA"


def test_the_second_process_is_the_one_that_could_lose_it(tmp_path: Path) -> None:
    """Guard the guard: if the re-exec stopped happening, the test above would
    pass for the wrong reason -- a single process never had the SHA to lose."""
    script = _prologue(tmp_path)
    env = {"PATH": f"{_stub_git(tmp_path)}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env, timeout=60, check=True)

    assert "Restarting deploy with the updated script" in result.stdout
    assert result.stdout.count("Updating ") == 2
