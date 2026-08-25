"""Tests for the wiki registry job entrypoint."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import wiki_registry_refresh as job  # noqa: E402


@pytest.fixture(autouse=True)
def _database(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")


def test_a_run_with_no_replica_succeeds_and_says_why(monkeypatch, capsys):
    """The whole point of the cadence: a missing replica is not a failed week."""
    monkeypatch.setattr(
        job.wiki_registry,
        "refresh",
        lambda: {"read": 0, "added": 0, "updated": 0, "retired": 0, "reason": "no-credentials"},
    )

    assert job.main() == 0

    assert "wiki-registry: read=0 added=0 updated=0 retired=0 reason=no-credentials" in capsys.readouterr().out


def test_an_ordinary_run_prints_no_reason(monkeypatch, capsys):
    """A field that is almost always empty trains the reader to skip the line."""
    monkeypatch.setattr(
        job.wiki_registry,
        "refresh",
        lambda: {"read": 1028, "added": 0, "updated": 3, "retired": 1, "reason": ""},
    )

    assert job.main() == 0

    out = capsys.readouterr().out
    assert "wiki-registry: read=1028 added=0 updated=3 retired=1\n" in out
    assert "reason=" not in out
