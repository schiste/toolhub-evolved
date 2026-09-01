# SPDX-License-Identifier: GPL-3.0-or-later
"""Stamping wiki-hosted tools with the date their source was last edited.

No replica is reached. What matters is the seam either side of it: that the
newest revision wins where a creation date takes the oldest, that a stamp only
ever moves forward, that a row already holding the right answer is not rewritten
just to hold it again, and that a host with no replica finishes its census
normally with the dates simply absent.

The mirror-image module is `backend.gadget_creation_dates`, tested next door.
The differences worth their own tests here are the direction of the fold, the
forward-only rule, and the fact that this one re-offers every row on every pass
where a creation date is written once and left alone.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, wiki_edit_dates as edits, wiki_replica  # noqa: E402
from backend.models import UserScriptPage, WikiGadget  # noqa: E402

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


def declare(name, *pages, wiki=FRWIKI, touched=""):
    with db.session_scope() as session:
        session.add(
            WikiGadget(wiki=wiki, name=name, name_key=name.casefold(), pages=list(pages), touched_at_wiki=touched)
        )


def store(title, *, wiki=FRWIKI, touched="", deleted=None):
    with db.session_scope() as session:
        session.add(UserScriptPage(wiki=wiki, title=title, touched_at_wiki=touched, deleted_at=deleted))


def gadget_stamps(wiki=FRWIKI):
    with db.session_scope() as session:
        rows = session.query(WikiGadget).filter(WikiGadget.wiki == wiki).all()
        return {row.name: row.touched_at_wiki for row in rows}


def script_stamps(wiki=FRWIKI):
    with db.session_scope() as session:
        rows = session.query(UserScriptPage).filter(UserScriptPage.wiki == wiki).all()
        return {row.title: row.touched_at_wiki for row in rows}


# --- gadgets: the newest page wins -----------------------------------------


def test_a_gadget_is_stamped_with_its_code_pages_latest_revision():
    declare("HotCat", "HotCat.js")
    written = edits.backfill_gadgets(
        [FRWIKI],
        connect=Replica({"frwiki": [("Gadget-HotCat.js", "20250311120000")]}).connect,
    )
    assert written == {FRWIKI: 1}
    assert gadget_stamps() == {"HotCat": "20250311120000"}


def test_the_newest_of_several_files_dates_the_whole_gadget():
    """Any one file being edited is the gadget being edited."""
    declare("HotCat", "HotCat.js", "HotCat.css")
    edits.backfill_gadgets(
        [FRWIKI],
        connect=Replica(
            {"frwiki": [("Gadget-HotCat.js", "20190101000000"), ("Gadget-HotCat.css", "20240607083000")]},
        ).connect,
    )
    assert gadget_stamps() == {"HotCat": "20240607083000"}


def test_a_file_name_written_with_spaces_still_matches_the_stored_page():
    declare("Live preview", "Live preview.js")
    edits.backfill_gadgets(
        [FRWIKI],
        connect=Replica({"frwiki": [("Gadget-Live_preview.js", "20230101000000")]}).connect,
    )
    assert gadget_stamps() == {"Live preview": "20230101000000"}


def test_a_page_outside_the_gadget_prefix_dates_nothing():
    declare("HotCat", "HotCat.js")
    rows = [("Gadgets-definition", "20260101000000"), ("Common.js", "20260101000000")]
    assert edits.backfill_gadgets([FRWIKI], connect=Replica({"frwiki": rows}).connect) == {FRWIKI: 0}
    assert gadget_stamps() == {"HotCat": ""}


def test_a_gadget_whose_code_lives_elsewhere_is_left_undated():
    """No row, no date -- rather than the day this census happened to run."""
    declare("Imported", "Imported.js")
    assert edits.backfill_gadgets([FRWIKI], connect=Replica({"frwiki": []}).connect) == {FRWIKI: 0}
    assert gadget_stamps() == {"Imported": ""}


# --- the forward-only rule -------------------------------------------------


def test_a_newer_edit_replaces_the_stamp_a_previous_run_wrote():
    declare("HotCat", "HotCat.js", touched="20240101000000")
    written = edits.backfill_gadgets(
        [FRWIKI],
        connect=Replica({"frwiki": [("Gadget-HotCat.js", "20260220091500")]}).connect,
    )
    assert written == {FRWIKI: 1}
    assert gadget_stamps() == {"HotCat": "20260220091500"}


def test_an_older_answer_never_moves_a_stamp_backwards():
    """A replica lagging behind must not un-publish an edit already recorded."""
    declare("HotCat", "HotCat.js", touched="20260220091500")
    written = edits.backfill_gadgets(
        [FRWIKI],
        connect=Replica({"frwiki": [("Gadget-HotCat.js", "20240101000000")]}).connect,
    )
    assert written == {FRWIKI: 0}
    assert gadget_stamps() == {"HotCat": "20260220091500"}


def test_a_row_that_already_holds_the_answer_is_not_rewritten():
    """The census runs hourly; rewriting every row each tick to change nothing
    would hold locks against everything else on the table for no result."""
    declare("HotCat", "HotCat.js", touched="20260220091500")
    written = edits.backfill_gadgets(
        [FRWIKI],
        connect=Replica({"frwiki": [("Gadget-HotCat.js", "20260220091500")]}).connect,
    )
    assert written == {FRWIKI: 0}


# --- user script pages -----------------------------------------------------


def test_a_script_page_is_stamped_by_its_normalized_title():
    store("Utilisateur:Lupin/popups.js")
    written = edits.backfill_scripts(
        [FRWIKI],
        connect=Replica({"frwiki": [("Lupin/popups.js", "20251104071200")]}).connect,
    )
    assert written == {FRWIKI: 1}
    assert script_stamps() == {"Utilisateur:Lupin/popups.js": "20251104071200"}


def test_a_page_the_replica_has_never_heard_of_stays_blank():
    store("Utilisateur:Ghost/gone.js")
    assert edits.backfill_scripts([FRWIKI], connect=Replica({"frwiki": []}).connect) == {FRWIKI: 0}
    assert script_stamps() == {"Utilisateur:Ghost/gone.js": ""}


def test_a_page_the_census_has_marked_deleted_is_still_dated():
    """Its last edit is a true fact, and is what a reader asking why it went wants."""
    store("Utilisateur:Lupin/old.js", deleted=datetime(2026, 3, 1))
    edits.backfill_scripts(
        [FRWIKI],
        connect=Replica({"frwiki": [("Lupin/old.js", "20180401000000")]}).connect,
    )
    assert script_stamps() == {"Utilisateur:Lupin/old.js": "20180401000000"}


def test_a_sweep_stamp_that_is_already_current_is_left_alone():
    store("Utilisateur:Lupin/popups.js", touched="20251104071200")
    written = edits.backfill_scripts(
        [FRWIKI],
        connect=Replica({"frwiki": [("Lupin/popups.js", "20251104071200")]}).connect,
    )
    assert written == {FRWIKI: 0}


# --- hosts without a replica ------------------------------------------------


def test_a_host_without_credentials_stamps_nothing_and_raises_nothing(monkeypatch):
    monkeypatch.setattr(wiki_replica, "credentials", lambda: None)
    declare("HotCat", "HotCat.js")
    store("Utilisateur:Lupin/popups.js")
    assert edits.backfill_gadgets([FRWIKI], connect=Replica({}).connect) == {}
    assert edits.backfill_scripts([FRWIKI], connect=Replica({}).connect) == {}
    assert gadget_stamps() == {"HotCat": ""}


def test_a_wiki_meta_p_does_not_name_is_skipped_and_the_others_run():
    declare("HotCat", "HotCat.js")
    declare("Navigation", "Navigation.js", wiki=METAWIKI)
    replica = Replica(
        {"metawiki": [("Gadget-Navigation.js", "20250505050505")]},
        dbnames={METAWIKI: "metawiki"},
    )
    written = edits.backfill_gadgets([FRWIKI, METAWIKI], connect=replica.connect)
    assert written == {METAWIKI: 1}
    assert gadget_stamps() == {"HotCat": ""}
    assert gadget_stamps(METAWIKI) == {"Navigation": "20250505050505"}


def test_one_wikis_outage_does_not_hide_another_wikis_dates():
    declare("HotCat", "HotCat.js")
    declare("Navigation", "Navigation.js", wiki=METAWIKI)
    replica = Replica(
        {"metawiki": [("Gadget-Navigation.js", "20250505050505")]},
        unreachable=("frwiki",),
    )
    written = edits.backfill_gadgets([FRWIKI, METAWIKI], connect=replica.connect)
    assert written == {METAWIKI: 1}
    assert gadget_stamps() == {"HotCat": ""}


def test_a_wiki_meta_p_does_not_name_is_skipped_and_the_other_scripts_run():
    store("Utilisateur:Lupin/popups.js")
    store("User:Zoe/toc.js", wiki=METAWIKI)
    replica = Replica(
        {"metawiki": [("Zoe/toc.js", "20250505050505")]},
        dbnames={METAWIKI: "metawiki"},
    )

    written = edits.backfill_scripts([FRWIKI, METAWIKI], connect=replica.connect)

    assert written == {METAWIKI: 1}
    assert script_stamps() == {"Utilisateur:Lupin/popups.js": ""}


def test_one_wikis_outage_does_not_hide_another_wikis_script_dates():
    store("Utilisateur:Lupin/popups.js")
    store("User:Zoe/toc.js", wiki=METAWIKI)
    replica = Replica(
        {"metawiki": [("Zoe/toc.js", "20250505050505")]},
        unreachable=("frwiki",),
    )

    written = edits.backfill_scripts([FRWIKI, METAWIKI], connect=replica.connect)

    # The wiki that answered is stamped and the one that did not is left as it
    # was. Letting the outage out of here would abandon every wiki after it.
    assert written == {METAWIKI: 1}
    assert script_stamps() == {"Utilisateur:Lupin/popups.js": ""}
    assert script_stamps(METAWIKI) == {"User:Zoe/toc.js": "20250505050505"}
