# SPDX-License-Identifier: GPL-3.0-or-later
"""A lock conflict undoes the work, so the work is worth doing again."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db  # noqa: E402


def _lock_error(errno):
    """Mimic what PyMySQL raises when MariaDB rolls a transaction back."""
    return OperationalError("UPDATE ...", {}, Exception(errno, "lock conflict"))


@pytest.mark.parametrize("errno", db.TRANSIENT_LOCK_ERRNOS)
def test_deadlock_and_lock_wait_are_both_recognised(errno):
    assert db.is_transient_lock_error(_lock_error(errno)) is True


def test_an_unrelated_database_error_is_not_a_lock_conflict():
    assert db.is_transient_lock_error(OperationalError("SELECT 1", {}, Exception(2006, "gone away"))) is False
    assert db.is_transient_lock_error(IntegrityError("INSERT", {}, Exception(1062, "duplicate"))) is False
    # No wrapped driver error at all, so nothing says the work was undone.
    assert db.is_transient_lock_error(OperationalError("SELECT 1", {}, None)) is False


def test_work_that_succeeds_first_time_is_not_repeated():
    calls = []
    assert db.run_with_lock_retry(lambda: calls.append(1) or "done", sleep=lambda _s: None) == "done"
    assert len(calls) == 1


def test_work_undone_by_a_lock_conflict_is_retried_and_can_succeed():
    attempts = []
    waits = []

    def work():
        attempts.append(1)
        if len(attempts) < 3:
            raise _lock_error(1213)
        return "eventually"

    assert db.run_with_lock_retry(work, sleep=waits.append) == "eventually"
    assert len(attempts) == 3
    # Backoff grows, so a busy moment is not hammered at a fixed interval.
    assert waits == [db.LOCK_RETRY_BACKOFF_SECONDS, db.LOCK_RETRY_BACKOFF_SECONDS * 2]


def test_a_persistent_conflict_surfaces_the_database_error():
    attempts = []

    def work():
        attempts.append(1)
        raise _lock_error(1205)

    with pytest.raises(OperationalError):
        db.run_with_lock_retry(work, attempts=2, sleep=lambda _s: None)
    # Bounded: it gives up rather than retrying a genuinely stuck conflict.
    assert len(attempts) == 2


def test_an_error_that_is_not_a_lock_conflict_is_raised_immediately():
    attempts = []

    def work():
        attempts.append(1)
        raise IntegrityError("INSERT", {}, Exception(1062, "duplicate"))

    with pytest.raises(IntegrityError):
        db.run_with_lock_retry(work, sleep=lambda _s: None)
    # Retrying a constraint violation would just repeat it.
    assert len(attempts) == 1
