# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the scheduled-job definitions that jobs.yaml already declares.

jobs.yaml is the single source of truth for what runs in the background, so
/workers reads it rather than repeating the list in Python where the two could
drift. PyYAML is not a runtime dependency and this file is a flat list of
scalar-valued maps with leading comments, so a small reader covers it exactly;
tests assert it against the real file so a shape change fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

JOBS_FILE = Path(__file__).resolve().parents[2] / "jobs.yaml"
# A continuous job declares no cron line, so there is no period to read off one.
# It publishes a heartbeat run instead, and this is that period: it must match
# repository_scan.HEARTBEAT_SECONDS, which a test pins, or /workers would call a
# perfectly healthy worker late.
CONTINUOUS_HEARTBEAT_MINUTES = 5
# Cron field count; anything else is not a schedule this reader understands.
CRON_FIELDS = 5
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080
DAYS_PER_LONG_MONTH = 31


@dataclass(frozen=True)
class ScheduledJob:
    """One background worker as declared for the Toolforge jobs framework."""

    name: str
    schedule: str
    description: str
    timeout_seconds: int
    continuous: bool = False

    @property
    def expected_interval_minutes(self) -> int:
        """Return how often this job is expected to run, 0 when unknown."""
        if self.continuous:
            return CONTINUOUS_HEARTBEAT_MINUTES
        return _interval_minutes(self.schedule)


def _interval_minutes(schedule: str) -> int:  # noqa: PLR0911 - one return per cron shape stays readable
    """Approximate a cron expression's period for staleness comparison.

    Deliberately coarse: this decides how long a silence is normal, so it only
    has to distinguish minutes from hours from days. Unknown shapes return 0
    and the caller reports "unknown" rather than inventing a threshold.
    """
    fields = schedule.split()
    if len(fields) != CRON_FIELDS:
        return 0
    minute, hour, day_of_month, _month, day_of_week = fields
    if minute == "*":
        return 1
    if minute.startswith("*/") and hour == "*":
        step = minute.removeprefix("*/")
        return int(step) if step.isdigit() else 0
    if hour == "*":
        return MINUTES_PER_HOUR
    if hour.startswith("*/"):
        step = hour.removeprefix("*/")
        return int(step) * MINUTES_PER_HOUR if step.isdigit() else 0
    if day_of_week != "*":
        return MINUTES_PER_WEEK
    if day_of_month == "*":
        return MINUTES_PER_DAY
    days = sorted({int(value) for value in day_of_month.split(",") if value.isdigit()})
    if days:
        circular_gaps = [right - left for left, right in pairwise(days)]
        circular_gaps.append(DAYS_PER_LONG_MONTH - days[-1] + days[0])
        return max(circular_gaps) * MINUTES_PER_DAY
    return 0


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":  # noqa: PLR2004 - a quoted scalar
        return value[1:-1]
    return value


@dataclass
class _Block:
    """The scalar fields of the job block currently being read."""

    schedule: str = ""
    timeout: int = 0
    continuous: bool = False


def _field(line: str, block: _Block) -> None:
    """Apply one scalar line from a job block, leaving unknown keys alone."""
    if line.startswith("schedule:"):
        block.schedule = _unquote(line.removeprefix("schedule:"))
    elif line.startswith("timeout:"):
        value = _unquote(line.removeprefix("timeout:"))
        block.timeout = int(value) if value.isdigit() else 0
    elif line.startswith("continuous:"):
        block.continuous = _unquote(line.removeprefix("continuous:")).lower() == "true"


def load(path: Path | None = None) -> list[ScheduledJob]:
    """Return every declared job in file order, with its leading comment."""
    source = path or JOBS_FILE
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    jobs: list[ScheduledJob] = []
    name = ""
    block = _Block()
    comment: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if name:
            jobs.append(
                ScheduledJob(
                    name=name,
                    schedule=block.schedule,
                    description=" ".join(comment).strip(),
                    timeout_seconds=block.timeout,
                    continuous=block.continuous,
                )
            )

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("- name:"):
            flush()
            name = _unquote(stripped.removeprefix("- name:"))
            block = _Block()
            comment = pending
            pending = []
        elif stripped.startswith("#"):
            # Comments inside a block describe the job it belongs to; any
            # before the first "- name:" wait for the block they introduce.
            target = comment if name else pending
            target.append(stripped.lstrip("#").strip())
        elif not stripped or stripped == "---":
            # A blank line or the document marker ends whatever comment block
            # was accumulating, so the file header never becomes job one's
            # description.
            pending = []
        else:
            _field(stripped, block)
    flush()
    return jobs
