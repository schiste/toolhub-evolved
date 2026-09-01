# SPDX-License-Identifier: GPL-3.0-or-later
"""Two jobs starting together must not race each other out of a schema."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db  # noqa: E402


def _exists_error():
    """Mimic what PyMySQL raises when another job created the table first."""
    return OperationalError(
        "CREATE TABLE user_tool_resolver_cache ...",
        {},
        Exception(db.TABLE_EXISTS_ERRNO, "Table 'user_tool_resolver_cache' already exists"),
    )


def test_a_table_someone_else_created_is_recognised():
    assert db._is_table_exists_error(_exists_error()) is True


def test_an_unrelated_database_error_is_not_a_table_that_exists():
    assert db._is_table_exists_error(IntegrityError("INSERT", {}, Exception(1062, "duplicate"))) is False
    assert db._is_table_exists_error(OperationalError("SELECT 1", {}, None)) is False


def _patched_create_all(monkeypatch, outcomes):
    """Drive create_all through `outcomes`, recording how often it was called."""
    calls = []

    def create_all(_engine):
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(db, "engine", lambda: object())
    monkeypatch.setattr(db.Base.metadata, "create_all", create_all)
    return calls


def test_losing_the_race_to_create_a_table_is_not_a_failed_run(monkeypatch):
    calls = _patched_create_all(monkeypatch, [_exists_error(), None])

    db._create_missing_tables()

    # The second pass skips whatever now exists and creates whatever still
    # does not, which is why one retry settles any number of lost tables.
    assert len(calls) == 2


def test_a_create_that_keeps_failing_is_not_retried_forever(monkeypatch):
    calls = _patched_create_all(monkeypatch, [_exists_error(), _exists_error()])

    with pytest.raises(OperationalError):
        db._create_missing_tables()

    assert len(calls) == db.SCHEMA_CREATE_ATTEMPTS


def test_a_create_that_failed_for_another_reason_is_raised_at_once(monkeypatch):
    broken = OperationalError("CREATE TABLE ...", {}, Exception(1064, "syntax error"))
    calls = _patched_create_all(monkeypatch, [broken])

    with pytest.raises(OperationalError):
        db._create_missing_tables()

    assert len(calls) == 1


# --- naming the connection that holds a lock ---


class _FakeConnection:
    """One connection that answers IS_USED_LOCK, or refuses to."""

    def __init__(self, answer):
        self._answer = answer

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def scalar(self, _statement, _params):
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _mysql(monkeypatch, answer):
    """Point `db.engine` at something that looks like MariaDB and answers `answer`."""

    class Engine:
        dialect = SimpleNamespace(name="mariadb")

        def connect(self):
            return _FakeConnection(answer)

    monkeypatch.setattr(db, "engine", Engine)


def test_the_connection_holding_a_lock_is_named_in_the_skip_report(monkeypatch):
    _mysql(monkeypatch, 4172)

    assert db.advisory_lock_holder("people-reconcile") == 4172


def test_a_lock_nobody_holds_names_nobody(monkeypatch):
    _mysql(monkeypatch, None)

    assert db.advisory_lock_holder("people-reconcile") is None


def test_a_lock_whose_holder_cannot_be_named_is_still_reported_as_a_skip(monkeypatch):
    # This only ever runs on the failure path of a job that is about to skip.
    # The report is worth more with the field missing than not written at all.
    _mysql(monkeypatch, OperationalError("SELECT IS_USED_LOCK", {}, Exception(2006, "gone away")))

    assert db.advisory_lock_holder("people-reconcile") is None


def test_sqlite_is_not_asked_a_question_only_mariadb_answers():
    db.configure("sqlite://")

    # `IS_USED_LOCK` is not SQL everywhere. Asking would raise on the one path
    # that exists to keep a skip report from failing.
    assert db.advisory_lock_holder("people-reconcile") is None
