# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeping a local roster of every Wikimedia wiki the census can read.

No replica is reached. What matters here is what the registry does with the
answer: that a wiki keeps its identity across refreshes, that one which left the
roster is marked rather than deleted, and -- the case that decides whether this
is safe to run weekly -- that a replica which cannot be reached leaves a
thousand-row table exactly as it was instead of retiring all of it.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, wiki_registry, wiki_replica  # noqa: E402
from backend.models import WikiProject  # noqa: E402

USER = wiki_replica.Credentials(user="s55555", password="sekrit")


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    with application.app_context():
        yield


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    monkeypatch.setattr(wiki_replica, "credentials", lambda: USER)


# --- fake replica ----------------------------------------------------------


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        """The statement is `wiki_replica`'s business, and is tested there."""

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return Cursor(self.rows)

    def close(self):
        """Nothing to release."""


def replica(rows):
    def connect(_user, _target):
        return Connection(rows)

    return connect


def row(dbname, host, section="s3", family="wikipedia", lang="xx", closed=0):
    return (dbname.encode(), f"https://{host}".encode(), family.encode(), lang.encode(), section.encode(), closed)


def stored():
    """Every registry row as (dbname, section, closed, retired_at), keyed by wiki."""
    with db.session_scope() as session:
        return {
            project.wiki: (project.dbname, project.section, project.closed, project.retired_at)
            for project in session.query(WikiProject).all()
        }


# --- refreshing ------------------------------------------------------------


def test_a_first_refresh_records_every_wiki_the_roster_named():
    summary = wiki_registry.refresh(
        connect=replica([row("frwiki", "fr.wikipedia.org", "s6"), row("enwiki", "en.wikipedia.org", "s1")])
    )
    assert (summary["read"], summary["added"], summary["updated"], summary["retired"]) == (2, 2, 0, 0)
    assert stored() == {
        "fr.wikipedia.org": ("frwiki", "s6", False, None),
        "en.wikipedia.org": ("enwiki", "s1", False, None),
    }


def test_a_second_refresh_that_learned_nothing_new_writes_nothing():
    """The registry runs weekly over a thousand rows; a no-op must be a no-op."""
    rows = [row("frwiki", "fr.wikipedia.org", "s6")]
    wiki_registry.refresh(connect=replica(rows))
    summary = wiki_registry.refresh(connect=replica(rows))
    assert (summary["read"], summary["added"], summary["updated"]) == (1, 0, 0)


def test_a_wiki_that_moved_section_is_updated_in_place():
    """Replica sections are rebalanced; a wiki that moved must not be re-added."""
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org", "s6")]))
    summary = wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org", "s4")]))
    assert (summary["added"], summary["updated"]) == (0, 1)
    assert stored()["fr.wikipedia.org"][1] == "s4"


def test_a_wiki_that_closed_stays_on_the_roster_and_says_so():
    wiki_registry.refresh(connect=replica([row("aawiki", "aa.wikipedia.org")]))
    wiki_registry.refresh(connect=replica([row("aawiki", "aa.wikipedia.org", closed=1)]))
    dbname, _section, closed, retired = stored()["aa.wikipedia.org"]
    assert (dbname, closed, retired) == ("aawiki", True, None)


# --- leaving the roster ----------------------------------------------------


def test_a_wiki_that_left_the_roster_is_marked_not_deleted():
    """Its pages are still in the census; forgetting it would orphan them."""
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org"), row("goneiki", "gone.example")]))
    summary = wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org")]))
    assert summary["retired"] == 1
    assert set(stored()) == {"fr.wikipedia.org", "gone.example"}
    assert stored()["gone.example"][3] is not None


def test_a_wiki_already_gone_is_not_retired_again():
    wiki_registry.refresh(connect=replica([row("goneiki", "gone.example")]))
    keep = [row("frwiki", "fr.wikipedia.org")]
    wiki_registry.refresh(connect=replica(keep))
    assert wiki_registry.refresh(connect=replica(keep))["retired"] == 0


def test_a_wiki_that_came_back_is_live_again():
    """A rename or a truncated read is not a wiki closing forever."""
    both = [row("frwiki", "fr.wikipedia.org"), row("backiki", "back.example")]
    wiki_registry.refresh(connect=replica(both))
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org")]))
    summary = wiki_registry.refresh(connect=replica(both))
    assert summary["updated"] == 1
    assert stored()["back.example"][3] is None


# --- when the replica is not there ----------------------------------------


def test_no_credentials_leaves_the_registry_alone_and_says_why(monkeypatch):
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org")]))
    monkeypatch.setattr(wiki_replica, "credentials", lambda: None)
    summary = wiki_registry.refresh(connect=replica([]))
    assert summary == {"read": 0, "added": 0, "updated": 0, "retired": 0, "reason": "no-credentials"}
    assert set(stored()) == {"fr.wikipedia.org"}


def test_an_unreachable_replica_does_not_retire_the_whole_registry():
    """The failure mode worth a test: one bad read must not erase a thousand wikis."""
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org"), row("enwiki", "en.wikipedia.org")]))

    def refuse(_user, _target):
        message = "connection refused"
        raise OSError(message)

    summary = wiki_registry.refresh(connect=refuse)
    assert summary["read"] == 0
    assert summary["reason"] == "unreadable:OSError"
    assert [entry[3] for entry in stored().values()] == [None, None]


def test_an_empty_roster_is_treated_as_a_bad_read_not_as_the_end_of_the_wikis():
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org")]))
    summary = wiki_registry.refresh(connect=replica([]))
    assert summary["reason"] == "empty"
    assert stored()["fr.wikipedia.org"][3] is None


# --- reading it back -------------------------------------------------------


def test_projects_come_back_grouped_by_section_so_a_pass_can_share_connections():
    wiki_registry.refresh(
        connect=replica(
            [
                row("frwiki", "fr.wikipedia.org", "s6"),
                row("aawiki", "aa.wikipedia.org", "s3"),
                row("abwiki", "ab.wikipedia.org", "s3"),
                row("enwiki", "en.wikipedia.org", "s1"),
            ]
        )
    )
    assert [project.section for project in wiki_registry.projects()] == ["s1", "s3", "s3", "s6"]


def test_a_retired_wiki_is_not_offered_for_reading():
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org"), row("goneiki", "gone.example")]))
    wiki_registry.refresh(connect=replica([row("frwiki", "fr.wikipedia.org")]))
    assert [project.wiki for project in wiki_registry.projects()] == ["fr.wikipedia.org"]
    assert len(wiki_registry.projects(include_retired=True)) == 2


def test_closed_wikis_are_offered_by_default_because_their_scripts_are_real():
    wiki_registry.refresh(
        connect=replica([row("frwiki", "fr.wikipedia.org"), row("aawiki", "aa.wikipedia.org", closed=1)])
    )
    assert len(wiki_registry.projects()) == 2
    assert [project.wiki for project in wiki_registry.projects(include_closed=False)] == ["fr.wikipedia.org"]
