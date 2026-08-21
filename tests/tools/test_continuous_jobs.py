# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the list of workers a deploy has to restart by hand.

Scheduled jobs pick up new code on their next tick, because each tick starts a
fresh pod. Continuous ones do not: `toolforge jobs load` leaves a job whose
definition is unchanged exactly as it is, so the pod keeps the modules it
imported when it started. Whatever this script prints is what the deploy
restarts, so a name it misses is a worker that silently serves the previous
release.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "continuous_jobs.sh"
JOBS = ROOT / "jobs.yaml"


def list_continuous(jobs_file: Path) -> list[str]:
    result = subprocess.run(
        ["sh", str(SCRIPT), str(jobs_file)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


def declared_job_names(jobs_file: Path) -> set[str]:
    prefix = "- name: "
    return {line[len(prefix) :].strip() for line in jobs_file.read_text().splitlines() if line.startswith(prefix)}


def test_the_repository_scanner_is_listed_and_every_name_is_a_real_job():
    """Against the real jobs.yaml, not a fixture that agrees with the parser."""
    names = list_continuous(JOBS)

    assert "repository-analysis" in names
    # A parser that returned a stray comment word would still "find" something,
    # so check the names against the jobs the file actually declares.
    assert set(names) <= declared_job_names(JOBS)
    assert len(names) == len(set(names))


def test_prose_about_continuous_jobs_is_not_a_declaration(tmp_path):
    """jobs.yaml explains at length why the scanner is continuous and the guard is not."""
    jobs = tmp_path / "jobs.yaml"
    jobs.write_text(
        "- name: talkative\n"
        "  # continuous: true\n"
        "  # ... which under a restarting continuous job would exit 0 forever.\n"
        "  command: /bin/true\n"
        "  schedule: '@hourly'\n"
    )

    assert list_continuous(jobs) == []


def test_a_job_that_opted_out_is_left_alone(tmp_path):
    jobs = tmp_path / "jobs.yaml"
    jobs.write_text("- name: scheduled\n  continuous: false\n  command: /bin/true\n")

    assert list_continuous(jobs) == []


def test_every_continuous_job_is_listed_not_just_the_first(tmp_path):
    """The deploy restarts what this prints, so stopping early would strand the rest."""
    jobs = tmp_path / "jobs.yaml"
    jobs.write_text(
        "- name: first\n  continuous: true\n  command: /bin/true\n"
        "\n"
        "- name: middle\n  command: /bin/true\n  schedule: '@daily'\n"
        "\n"
        "- name: last\n  continuous: true\n  command: /bin/true\n"
    )

    assert list_continuous(jobs) == ["first", "last"]


def test_a_missing_jobs_file_fails_loudly(tmp_path):
    """Printing nothing would read as 'no continuous jobs' and skip every restart."""
    result = subprocess.run(
        ["sh", str(SCRIPT), str(tmp_path / "absent.yaml")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "no such file" in result.stderr
