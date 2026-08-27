# SPDX-License-Identifier: GPL-3.0-or-later
"""Stamping user script pages with the date the wiki says they were created.

No replica is reached. What matters here is the seam either side of it: that a
census title and a replica title agree on being the same page, that a page the
replica has never heard of does not trap the backfill in a loop, and that a host
without replica credentials -- a laptop, CI, everything that is not Toolforge --
finishes the census normally with the dates simply absent.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_creation_dates as creation, wiki_replica  # noqa: E402
from backend.models import UserScriptPage  # noqa: E402

FRWIKI = "fr.wikipedia.org"
METAWIKI = "meta.wikimedia.org"
USER = wiki_replica.Credentials(user="s55555", password="sekrit")
DBNAMES = {FRWIKI: "frwiki", METAWIKI: "metawiki"}


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    """Default every test to a host that has replica credentials."""
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


class Replica:
    """Answers `meta_p` from a host map and each wiki database from a page map."""

    def __init__(self, pages, *, dbnames=None, unreachable=()):
        self.pages = pages
        self.dbnames = DBNAMES if dbnames is None else dbnames
        self.unreachable = set(unreachable)
        self.opened = []

    def connect(self, user, target):
        assert user == USER
        # `target.database` is the replica's `<dbname>_p`; the fakes are keyed
        # by the bare dbname, which is what a caller would recognise.
        dbname = target.database.removesuffix("_p")
        if dbname in self.unreachable:
            raise OSError(dbname)
        self.opened.append(dbname)
        return Connection(self._rows(dbname))

    def _rows(self, dbname):
        if dbname == wiki_replica.META_DB:
            return tuple((name, wiki_replica.url_for(wiki)) for wiki, name in self.dbnames.items())
        return tuple(self.pages.get(dbname, ()))


# --- helpers ---------------------------------------------------------------


def store(*titles, wiki=FRWIKI, created="", author=""):
    with db.session_scope() as session:
        for title in titles:
            session.add(
                UserScriptPage(wiki=wiki, title=title, created_at_wiki=created, first_author_wiki=author)
            )


def stamps(wiki=FRWIKI):
    with db.session_scope() as session:
        rows = session.query(UserScriptPage).filter(UserScriptPage.wiki == wiki).all()
        return {row.title: row.created_at_wiki for row in rows}


def authors(wiki=FRWIKI):
    with db.session_scope() as session:
        rows = session.query(UserScriptPage).filter(UserScriptPage.wiki == wiki).all()
        return {row.title: row.first_author_wiki for row in rows}


# --- matching census titles to replica titles ------------------------------


def test_a_page_is_stamped_with_the_date_the_replica_reports():
    store("Utilisateur:Tom/monobook.js")
    written = creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Tom/monobook.js", "20090412183000", "Tom")]}).connect,
    )
    assert written == {FRWIKI: 1}
    assert stamps() == {"Utilisateur:Tom/monobook.js": "20090412183000"}


def test_a_title_whose_spaces_the_wiki_writes_as_underscores_still_matches():
    """The census stores the display title; the replica stores `page_title`."""
    store("Utilisateur:Tom Smith/monobook.js")
    creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Tom_Smith/monobook.js", "20080101000000", "Tom Smith")]}).connect,
    )
    assert stamps() == {"Utilisateur:Tom Smith/monobook.js": "20080101000000"}


def test_a_page_the_replica_has_never_heard_of_is_left_blank():
    store("Utilisateur:Gone/deleted.js")
    written = creation.backfill([FRWIKI], connect=Replica({"frwiki": []}).connect)
    assert written == {FRWIKI: 0}
    assert stamps() == {"Utilisateur:Gone/deleted.js": ""}


def test_one_missing_page_does_not_stop_the_rest_of_its_batch():
    """A wiki always has a few of these: pages deleted between sweep and stamp."""
    store("Utilisateur:Tom/monobook.js", "Utilisateur:Gone/deleted.js", "Utilisateur:Ann/vector.js")
    rows = [("Tom/monobook.js", "20090412183000", "Tom"), ("Ann/vector.js", "20140228120000", "Ann")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 2}
    assert stamps() == {
        "Utilisateur:Tom/monobook.js": "20090412183000",
        "Utilisateur:Gone/deleted.js": "",
        "Utilisateur:Ann/vector.js": "20140228120000",
    }


def test_a_dated_page_keeps_its_date_even_when_the_replica_disagrees():
    """A stamped date is settled; a later reading of it does not overwrite one."""
    store("Utilisateur:Tom/monobook.js", created="20090412183000", author="Tom")
    written = creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Tom/monobook.js", "29991231000000", "Tom")]}).connect,
    )
    assert written == {FRWIKI: 0}
    assert stamps() == {"Utilisateur:Tom/monobook.js": "20090412183000"}


def test_a_page_dated_before_authors_were_read_gains_one_without_losing_its_date():
    """Every page in the table was stamped before this lane asked who wrote it."""
    store("Utilisateur:Tom/monobook.js", created="20090412183000")
    written = creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Tom/monobook.js", "20090412183000", "Dr Brains")]}).connect,
    )
    assert written == {FRWIKI: 1}
    assert stamps() == {"Utilisateur:Tom/monobook.js": "20090412183000"}
    assert authors() == {"Utilisateur:Tom/monobook.js": "Dr Brains"}


def test_a_fully_stamped_page_costs_the_next_run_no_write_at_all():
    """A timestamps-only UPDATE across the corpus is a lock wait that buys nothing."""
    store("Utilisateur:Tom/monobook.js", created="20090412183000", author="Tom")
    written = creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Tom/monobook.js", "20090412183000", "Tom")]}).connect,
    )
    assert written == {FRWIKI: 0}


def test_the_first_editor_is_recorded_even_when_it_is_not_the_page_owner():
    """954 of frwiki's 14,433 script pages were first written by somebody else."""
    store("Utilisateur:Tom/monobook.js")
    creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Tom/monobook.js", "20090412183000", "Dr Brains")]}).connect,
    )
    assert authors() == {"Utilisateur:Tom/monobook.js": "Dr Brains"}


def test_a_page_whose_first_author_was_suppressed_is_still_dated():
    """The edit happened; MediaWiki has withdrawn only the name on it."""
    store("Utilisateur:Tom/monobook.js")
    written = creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Tom/monobook.js", "20090412183000", "")]}).connect,
    )
    assert written == {FRWIKI: 1}
    assert stamps() == {"Utilisateur:Tom/monobook.js": "20090412183000"}
    assert authors() == {"Utilisateur:Tom/monobook.js": ""}


def test_another_wikis_pages_are_not_stamped_from_this_wikis_replica():
    store("User:Tom/monobook.js", wiki=METAWIKI)
    creation.backfill([FRWIKI], connect=Replica({"frwiki": [("Tom/monobook.js", "20090412183000", "Tom")]}).connect)
    assert stamps(METAWIKI) == {"User:Tom/monobook.js": ""}


# --- paging ----------------------------------------------------------------


def test_more_pages_than_one_batch_are_all_stamped(monkeypatch):
    """Paged by id, so the batch size must not decide how much gets written."""
    monkeypatch.setattr(creation, "BATCH", 2)
    titles = [f"Utilisateur:Tom/s{index}.js" for index in range(5)]
    store(*titles)
    rows = [(f"Tom/s{index}.js", f"2009010{index}000000", "Tom") for index in range(5)]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 5}
    assert stamps() == {title: f"2009010{index}000000" for index, title in enumerate(titles)}


def test_a_full_batch_of_unknown_pages_does_not_loop_forever(monkeypatch):
    """The rows stay blank, so a "what is still missing" loop would never end."""
    monkeypatch.setattr(creation, "BATCH", 2)
    store(*[f"Utilisateur:Gone/s{index}.js" for index in range(5)])
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": []}).connect) == {FRWIKI: 0}


def test_a_replica_with_nothing_to_say_costs_no_transaction():
    """An empty answer is the common case on a wiki with no scripts."""
    store("Utilisateur:Tom/monobook.js")
    assert creation.record(FRWIKI, {}) == 0


# --- hosts that have no replica --------------------------------------------


def test_a_host_without_replica_credentials_writes_nothing(monkeypatch):
    monkeypatch.setattr(wiki_replica, "credentials", lambda: None)
    store("Utilisateur:Tom/monobook.js")
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": []}).connect) == {}
    assert stamps() == {"Utilisateur:Tom/monobook.js": ""}


def test_an_unreachable_meta_database_writes_nothing():
    store("Utilisateur:Tom/monobook.js")
    replica = Replica({}, unreachable={wiki_replica.META_DB})
    assert creation.backfill([FRWIKI], connect=replica.connect) == {}


def test_one_wikis_outage_does_not_stop_the_next_wiki():
    store("Utilisateur:Tom/monobook.js")
    store("User:Tom/common.js", wiki=METAWIKI)
    replica = Replica(
        {"metawiki": [("Tom/common.js", "20120101000000", "Tom")]},
        unreachable={"frwiki"},
    )
    assert creation.backfill([FRWIKI, METAWIKI], connect=replica.connect) == {METAWIKI: 1}
    assert stamps() == {"Utilisateur:Tom/monobook.js": ""}
    assert stamps(METAWIKI) == {"User:Tom/common.js": "20120101000000"}


def test_a_wiki_meta_does_not_know_is_skipped_rather_than_guessed():
    """Deriving a database name locally would be a second source of truth."""
    store("Utilisateur:Tom/monobook.js", wiki="scripts.example.org")
    replica = Replica({}, dbnames={})
    assert creation.backfill(["scripts.example.org"], connect=replica.connect) == {}
    assert replica.opened == [wiki_replica.META_DB]
