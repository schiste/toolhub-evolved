# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading jobs.yaml for the facts the connection grant depends on.

`db.CONCURRENT_JOB_PROCESSES` was hand-written and two jobs were added beside
it on 2026-09-06 without it moving, so the budget test kept passing against a
number that no longer described anything and production returned
`max_user_connections` on the job that carries every projection change.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, job_catalog  # noqa: E402


def test_the_process_ceiling_counts_the_busiest_minute_not_the_average(tmp_path):
    """Coincidence is what the connection grant has to survive.

    A job at :47 and one every fifteen minutes only contend when both fire, so
    the account has to cover that minute rather than a typical one.
    """
    path = tmp_path / "jobs.yaml"
    path.write_text(
        '- name: every-minute\n  schedule: "* * * * *"\n  command: a\n  image: i\n'
        '- name: quarter-hourly\n  schedule: "*/15 * * * *"\n  command: b\n  image: i\n'
        '- name: at-seventeen\n  schedule: "17 * * * *"\n  command: c\n  image: i\n'
    )

    # :00 has the every-minute job and the quarter-hourly one; :17 has the
    # every-minute job and the pinned one. Two either way, never three.
    assert job_catalog.concurrent_process_ceiling(path) == 2


def test_a_continuous_job_counts_in_every_minute(tmp_path):
    """It is always alive, so it contends with whatever else fires."""
    path = tmp_path / "jobs.yaml"
    path.write_text(
        "- name: always\n  continuous: true\n  command: a\n  image: i\n"
        '- name: hourly\n  schedule: "5 * * * *"\n  command: b\n  image: i\n'
    )

    assert job_catalog.concurrent_process_ceiling(path) == 2


def test_the_declared_plan_is_measured_against_what_jobs_yaml_actually_starts():
    """The constant was hand-written and two jobs were added beside it.

    Pinned rather than asserted equal: the grant cannot supply the real
    ceiling, so raising the constant would only turn the budget test red. This
    fails when either number moves, which is what makes the gap visible.
    """
    # Equal, at last. 7 on 2026-09-06, 6 once wiki-registry and
    # catalog-integrity moved off :17, and 4 once the harmonics were broken:
    # */5, */10 and */15 all fired on the top of the hour together, and
    # people-reconcile-incremental ran every minute to do nothing between
    # projection bursts. Asserted equal rather than pinned separately, because
    # the plan and the measurement agreeing is the whole point -- a job added
    # without room for it now fails here instead of in production.
    assert job_catalog.concurrent_process_ceiling() == db.CONCURRENT_JOB_PROCESSES


def test_a_schedule_that_is_not_a_cron_line_fires_in_no_minute():
    """Same rule the interval reader uses: an unrecognised shape is not
    guessed at. Counting it as firing everywhere would inflate the ceiling the
    connection grant is measured against."""
    assert job_catalog._fires_at("", 0) is False
    assert job_catalog._fires_at("not a cron line", 17) is False


def test_a_step_of_zero_fires_in_no_minute_rather_than_dividing_by_it():
    assert job_catalog._fires_at("*/0 * * * *", 0) is False
