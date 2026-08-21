# SPDX-License-Identifier: GPL-3.0-or-later
"""Two jobs starting together must not race each other out of a schema."""

import sys
from pathlib import Path

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
