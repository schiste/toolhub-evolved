# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001, PLR2004, S101 - direct assertions cover fallback contracts
"""Tests for environment-backed job settings."""

import pytest

from backend.job_config import env_float, env_int


def test_env_int_falls_back_on_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOLHUB_TEST_INT", "not-an-integer")

    assert env_int("TOOLHUB_TEST_INT", 7) == 7


def test_env_float_falls_back_on_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOLHUB_TEST_FLOAT", "not-a-float")

    assert env_float("TOOLHUB_TEST_FLOAT", 1.5) == 1.5
