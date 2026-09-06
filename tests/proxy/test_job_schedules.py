# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduling invariants between jobs that write the same tables.

Two jobs can each be correct and still page an operator hourly if one starts
inside the window the other holds locks for. That is not visible in either
job's own file, so it is asserted here against jobs.yaml.
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import job_catalog  # noqa: E402

#: The long writer, and the hourly jobs that write the tables it writes.
#: `projection-refresh` rebuilds the identity projection: one measured pass
#: took 28.8 minutes and rewrote 3,379 `person_identifiers` rows, 23% of the
#: table, in a single burst.
LONG_WRITER = "projection-refresh"
PERSON_TABLE_HOURLY_JOBS = ("people-identity-reconcile",)


def _start_minute(schedule: str) -> int:
    """Return the fixed minute a schedule starts on."""
    minute = schedule.split()[0]
    assert minute.isdigit(), f"expected a fixed minute, got {schedule!r}"
    return int(minute)


@pytest.fixture(scope="module")
def declared():
    return {job.name: job for job in job_catalog.load()}


@pytest.mark.parametrize("name", PERSON_TABLE_HOURLY_JOBS)
def test_an_hourly_person_job_never_starts_inside_the_long_writers_window(name, declared):
    """The defect: `people-identity-reconcile` ran at :43, two minutes after
    `projection-refresh` started at :41, and collected 32 `Lock wait timeout
    exceeded` aborts on `UPDATE person_identifiers` -- one email each. It
    already retries lock aborts, but its budget is half its own timeout and
    cannot outlast a 29-minute hold, so the retry could never have fixed this.

    The window is the long writer's timeout, not its typical duration: the
    timeout is what it is *allowed* to hold for, and scheduling against a
    median is how this recurs the next time a run is slow.
    """
    writer, job = declared[LONG_WRITER], declared[name]
    start = _start_minute(writer.schedule)
    occupied = {(start + offset) % 60 for offset in range(math.ceil(writer.timeout_seconds / 60) + 1)}
    assert _start_minute(job.schedule) not in occupied, (
        f"{name} starts at :{_start_minute(job.schedule):02d}, inside {LONG_WRITER}'s "
        f"window of :{start:02d} + {writer.timeout_seconds // 60}m"
    )


def test_the_long_writers_window_still_leaves_an_hourly_slot_free(declared):
    """Raising that timeout is what makes the window swallow the hour.

    At 45 minutes the window covers three quarters of every clock hour and a
    free minute still exists. Past roughly 50 there is nowhere left to put an
    hourly job, and this fails rather than letting the next timeout increase
    silently recreate the collision it was placed around.
    """
    writer = declared[LONG_WRITER]
    occupied = math.ceil(writer.timeout_seconds / 60) + 1
    assert occupied < 60, f"{LONG_WRITER}'s timeout leaves no free minute in the hour"
