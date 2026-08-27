# SPDX-License-Identifier: GPL-3.0-or-later
"""Stamping gadgets with the date their code first existed on the wiki.

No replica is reached. What matters here is the seam either side of it: that a
file name a definition declares and a `page_title` the replica stores agree on
being the same page, that a gadget made of several files is dated by its oldest
one, and that a host without replica credentials finishes the census normally
with the dates simply absent.

The wiki lane's other creation-date module is tested next door in
`test_userscript_creation_dates`; the differences worth their own tests are the
`MediaWiki:Gadget-` prefix, the several-pages-to-one-gadget fold, and a
declaration that can gain an older page after the fact.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, gadget_creation_dates as creation, wiki_replica  # noqa: E402
from backend.models import WikiGadget  # noqa: E402

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


def declare(name, *pages, wiki=FRWIKI, created="", author=""):
    with db.session_scope() as session:
        session.add(
            WikiGadget(
                wiki=wiki,
                name=name,
                name_key=name.casefold(),
                pages=list(pages),
                created_at_wiki=created,
                first_author_wiki=author,
            )
        )


def stamps(wiki=FRWIKI):
    with db.session_scope() as session:
        rows = session.query(WikiGadget).filter(WikiGadget.wiki == wiki).all()
        return {row.name: row.created_at_wiki for row in rows}


def authors(wiki=FRWIKI):
    with db.session_scope() as session:
        rows = session.query(WikiGadget).filter(WikiGadget.wiki == wiki).all()
        return {row.name: row.first_author_wiki for row in rows}


# --- matching a declared file to a replica page ----------------------------


def test_a_gadget_is_stamped_with_its_code_pages_first_revision():
    declare("HotCat", "HotCat.js")
    written = creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Gadget-HotCat.js", "20070311120000", "Cacycle")]}).connect,
    )
    assert written == {FRWIKI: 1}
    assert stamps() == {"HotCat": "20070311120000"}


def test_a_file_name_written_with_spaces_still_matches_the_stored_page():
    """Definitions are written by hand; `page_title` uses underscores."""
    declare("Live preview", "Live preview.js")
    creation.backfill(
        [FRWIKI],
        connect=Replica({"frwiki": [("Gadget-Live_preview.js", "20060101000000", "Cacycle")]}).connect,
    )
    assert stamps() == {"Live preview": "20060101000000"}


def test_a_page_outside_the_gadget_prefix_dates_nothing():
    """`Gadgets-definition` is not a gadget, and neither is any other interface page."""
    declare("HotCat", "HotCat.js")
    rows = [("Gadgets-definition", "20050101000000", "Cacycle"), ("Common.js", "20040101000000", "Cacycle")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 0}
    assert stamps() == {"HotCat": ""}


# --- several pages, one gadget ---------------------------------------------


def test_a_gadget_of_several_files_is_dated_by_the_oldest_of_them():
    declare("HotCat", "HotCat.js", "HotCat.css", "HotCat-core.js")
    rows = [
        ("Gadget-HotCat.js", "20070311120000", "Cacycle"),
        ("Gadget-HotCat.css", "20050602090000", "Cacycle"),
        ("Gadget-HotCat-core.js", "20110101000000", "Cacycle"),
    ]
    creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect)
    assert stamps() == {"HotCat": "20050602090000"}


def test_a_gadget_is_dated_from_the_files_the_replica_does_know():
    """Code loaded from another wiki has no row here, and must not blank the rest."""
    declare("HotCat", "HotCat.js", "Elsewhere.js")
    rows = [("Gadget-HotCat.js", "20070311120000", "Cacycle")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 1}
    assert stamps() == {"HotCat": "20070311120000"}


def test_a_gadget_declaring_no_pages_is_left_blank():
    declare("Placeholder")
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": []}).connect) == {FRWIKI: 0}
    assert stamps() == {"Placeholder": ""}


# --- a declaration that changes ---------------------------------------------


def test_a_gadget_that_already_has_the_same_date_and_author_is_not_rewritten():
    """Re-reading is cheap; rewriting every row on every census tick is not."""
    declare("HotCat", "HotCat.js", created="20070311120000", author="Cacycle")
    rows = [("Gadget-HotCat.js", "20070311120000", "Cacycle")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 0}


def test_a_gadget_dated_before_authors_were_read_gains_one_in_place():
    """Every gadget in the table was stamped before this lane asked who wrote it."""
    declare("HotCat", "HotCat.js", created="20070311120000")
    rows = [("Gadget-HotCat.js", "20070311120000", "Cacycle")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 1}
    assert stamps() == {"HotCat": "20070311120000"}
    assert authors() == {"HotCat": "Cacycle"}


def test_the_author_is_taken_from_the_oldest_page_not_merely_any_of_them():
    """A gadget is credited to whoever started it, not to whoever added a file."""
    declare("HotCat", "HotCat.js", "HotCat.css")
    rows = [
        ("Gadget-HotCat.js", "20070311120000", "Someone Later"),
        ("Gadget-HotCat.css", "20050602090000", "Cacycle"),
    ]
    creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect)
    assert stamps() == {"HotCat": "20050602090000"}
    assert authors() == {"HotCat": "Cacycle"}


def test_a_date_moving_earlier_takes_the_credit_with_it():
    """The older file is now the first edit, so its author is now the author."""
    declare("HotCat", "HotCat.js", "HotCat.css", created="20070311120000", author="Someone Later")
    rows = [
        ("Gadget-HotCat.js", "20070311120000", "Someone Later"),
        ("Gadget-HotCat.css", "20050602090000", "Cacycle"),
    ]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 1}
    assert authors() == {"HotCat": "Cacycle"}


def test_a_gadget_whose_dating_page_left_the_declaration_stays_unattributed():
    """Its date came from a page nobody declares now; no remaining page wrote it."""
    declare("HotCat", "HotCat.js", created="20050602090000")
    rows = [("Gadget-HotCat.js", "20070311120000", "Someone Later")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 0}
    assert stamps() == {"HotCat": "20050602090000"}
    assert authors() == {"HotCat": ""}


def test_a_newly_declared_older_file_moves_the_date_earlier():
    """The gadget existed then; the definition only just admitted where."""
    declare("HotCat", "HotCat.js", "HotCat.css", created="20070311120000")
    rows = [("Gadget-HotCat.js", "20070311120000", "Cacycle"), ("Gadget-HotCat.css", "20050602090000", "Cacycle")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 1}
    assert stamps() == {"HotCat": "20050602090000"}


def test_a_dropped_old_file_does_not_move_the_date_later():
    """A gadget does not become younger because a file left the declaration."""
    declare("HotCat", "HotCat.js", created="20050602090000")
    rows = [("Gadget-HotCat.js", "20070311120000", "Cacycle")]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 0}
    assert stamps() == {"HotCat": "20050602090000"}


# --- scope and paging -------------------------------------------------------


def test_another_wikis_gadgets_are_not_stamped_from_this_wikis_replica():
    declare("HotCat", "HotCat.js", wiki=METAWIKI)
    creation.backfill([FRWIKI], connect=Replica({"frwiki": [("Gadget-HotCat.js", "20070311120000", "Cacycle")]}).connect)
    assert stamps(METAWIKI) == {"HotCat": ""}


def test_more_gadgets_than_one_batch_are_all_stamped(monkeypatch):
    monkeypatch.setattr(creation, "BATCH", 2)
    for index in range(5):
        declare(f"Gadget{index}", f"G{index}.js")
    rows = [(f"Gadget-G{index}.js", f"2007010{index}000000", "Cacycle") for index in range(5)]
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 5}
    assert stamps() == {f"Gadget{index}": f"2007010{index}000000" for index in range(5)}


def test_a_full_batch_of_undatable_gadgets_does_not_loop_forever(monkeypatch):
    """The rows stay blank, so a "what is still missing" loop would never end."""
    monkeypatch.setattr(creation, "BATCH", 2)
    for index in range(5):
        declare(f"Gadget{index}", f"G{index}.js")
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": []}).connect) == {FRWIKI: 0}


def test_a_replica_with_nothing_to_say_costs_no_transaction():
    declare("HotCat", "HotCat.js")
    assert creation.record(FRWIKI, {}) == 0


# --- hosts that have no replica --------------------------------------------


def test_a_host_without_replica_credentials_writes_nothing(monkeypatch):
    monkeypatch.setattr(wiki_replica, "credentials", lambda: None)
    declare("HotCat", "HotCat.js")
    assert creation.backfill([FRWIKI], connect=Replica({"frwiki": []}).connect) == {}
    assert stamps() == {"HotCat": ""}


def test_an_unreachable_meta_database_writes_nothing():
    declare("HotCat", "HotCat.js")
    replica = Replica({}, unreachable={wiki_replica.META_DB})
    assert creation.backfill([FRWIKI], connect=replica.connect) == {}


def test_one_wikis_outage_does_not_stop_the_next_wiki():
    declare("HotCat", "HotCat.js")
    declare("Navigation popups", "Popups.js", wiki=METAWIKI)
    replica = Replica(
        {"metawiki": [("Gadget-Popups.js", "20080101000000", "Cacycle")]},
        unreachable={"frwiki"},
    )
    assert creation.backfill([FRWIKI, METAWIKI], connect=replica.connect) == {METAWIKI: 1}
    assert stamps() == {"HotCat": ""}
    assert stamps(METAWIKI) == {"Navigation popups": "20080101000000"}


def test_a_wiki_meta_does_not_know_is_skipped_rather_than_guessed():
    declare("HotCat", "HotCat.js", wiki="gadgets.example.org")
    replica = Replica({}, dbnames={})
    assert creation.backfill(["gadgets.example.org"], connect=replica.connect) == {}
    assert replica.opened == [wiki_replica.META_DB]
