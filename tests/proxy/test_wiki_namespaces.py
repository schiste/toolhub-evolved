"""Storing what each wiki calls its user namespace, and handing it to the fold.

The fold in `backend.userscripts` used to know three spellings, which are the
ones the two wikis censused first happen to use. Everything here exists so that
a wiki nobody had thought of gets its own names read once and reused, and so
that a wiki that cannot be reached is no worse off than before this module.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, wiki_namespaces  # noqa: E402
from backend.models import WikiNamespaceSpelling, utcnow  # noqa: E402

DEWIKI = "de.wikipedia.org"


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


class FakeSiteinfo:
    """A wiki that answers siteinfo, counts how often it was asked, or refuses."""

    def __init__(self, names=("Benutzer",), *, fails=False):
        self.names = tuple(names)
        self.fails = fails
        self.asked = []

    def __call__(self, wiki, method, params):
        self.asked.append(wiki)
        if self.fails:
            raise RuntimeError("no route to host")
        canonical, *aliases = ("User", *self.names)
        return {
            "query": {
                "namespaces": {"2": {"id": 2, "canonical": canonical, "name": self.names[0]}},
                "namespacealiases": [{"id": 2, "alias": alias} for alias in aliases[1:]],
            },
        }


def row(wiki=DEWIKI):
    with db.session_scope() as session:
        found = session.get(WikiNamespaceSpelling, wiki)
        if found is None:
            return None
        return {
            "spellings": list(found.spellings or []),
            "read": found.read_at is not None,
            "checked": found.checked_at is not None,
            "status": found.status,
        }


# --- reading -----------------------------------------------------------------


def test_a_wiki_s_names_are_read_once_and_stored():
    wiki = FakeSiteinfo(("Benutzer", "Benutzerin"))
    assert wiki_namespaces.refresh(wiki, DEWIKI)["status"] == wiki_namespaces.STATUS_READ
    stored = row()
    assert stored["spellings"] == ["User", "Benutzer", "Benutzerin"]
    assert (stored["read"], stored["checked"]) == (True, True)


def test_a_wiki_that_cannot_be_reached_is_recorded_rather_than_raised():
    # One wiki refusing is not the census failing: the fold has a fallback and
    # the run has hundreds of other wikis to get through.
    assert wiki_namespaces.refresh(FakeSiteinfo(fails=True), DEWIKI)["status"] == wiki_namespaces.STATUS_UNREADABLE
    stored = row()
    assert (stored["spellings"], stored["read"], stored["checked"]) == ([], False, True)


def test_a_failed_read_keeps_the_spellings_it_already_had():
    wiki_namespaces.refresh(FakeSiteinfo(("Benutzer",)), DEWIKI)
    wiki_namespaces.refresh(FakeSiteinfo(fails=True), DEWIKI)
    stored = row()
    # Losing them would silently un-fold every dewiki title until the next
    # successful read, which is a worse outcome than never having read the wiki.
    assert stored["spellings"] == ["User", "Benutzer"]
    assert stored["status"] == wiki_namespaces.STATUS_UNREADABLE


def test_an_answer_with_no_user_namespace_is_unreadable_rather_than_empty():
    class Blank(FakeSiteinfo):
        def __call__(self, wiki, method, params):
            self.asked.append(wiki)
            return {"query": {"namespaces": {}}}

    assert wiki_namespaces.refresh(Blank(), DEWIKI)["status"] == wiki_namespaces.STATUS_UNREADABLE


# --- when to read again ------------------------------------------------------


def test_a_recent_reading_is_not_read_again():
    wiki = FakeSiteinfo()
    wiki_namespaces.refresh(wiki, DEWIKI)
    with db.session_scope() as session:
        assert wiki_namespaces.resolver(session, wiki)(DEWIKI) == ("User", "Benutzer")
    assert wiki.asked == [DEWIKI]


def test_a_reading_older_than_the_refresh_interval_is_read_again():
    wiki = FakeSiteinfo()
    wiki_namespaces.refresh(wiki, DEWIKI)
    with db.session_scope() as session:
        found = session.get(WikiNamespaceSpelling, DEWIKI)
        found.read_at = utcnow() - timedelta(days=wiki_namespaces.REFRESH_AFTER_DAYS + 1)
        found.checked_at = found.read_at
    with db.session_scope() as session:
        wiki_namespaces.resolver(session, wiki)(DEWIKI)
    assert wiki.asked == [DEWIKI, DEWIKI]


def test_a_wiki_that_just_refused_is_not_asked_again_by_the_next_resolver():
    # The two clocks earn their keep here. On `read_at` alone an unreadable wiki
    # is permanently stale, so every resolver built during a run -- and there
    # are several per sweep -- spends a request rediscovering that.
    wiki = FakeSiteinfo(fails=True)
    with db.session_scope() as session:
        wiki_namespaces.resolver(session, wiki)(DEWIKI)
    with db.session_scope() as session:
        assert wiki_namespaces.resolver(session, wiki)(DEWIKI) == ()
    assert wiki.asked == [DEWIKI]


def test_a_wiki_that_refused_long_enough_ago_is_tried_again():
    wiki = FakeSiteinfo(fails=True)
    with db.session_scope() as session:
        wiki_namespaces.resolver(session, wiki)(DEWIKI)
    with db.session_scope() as session:
        found = session.get(WikiNamespaceSpelling, DEWIKI)
        found.checked_at = utcnow() - timedelta(hours=wiki_namespaces.RETRY_AFTER_HOURS + 1)
    with db.session_scope() as session:
        wiki_namespaces.resolver(session, wiki)(DEWIKI)
    assert wiki.asked == [DEWIKI, DEWIKI]


# --- handing the names to the fold -------------------------------------------


def test_one_resolver_asks_about_a_wiki_once_however_often_it_is_named():
    # A sweep resolves the target namespace of every load edge on every page,
    # which is tens of thousands of lookups across a handful of wikis.
    wiki = FakeSiteinfo()
    with db.session_scope() as session:
        spellings = wiki_namespaces.resolver(session, wiki)
        assert [spellings(DEWIKI) for _ in range(50)] == [("User", "Benutzer")] * 50
    assert wiki.asked == [DEWIKI]


def test_a_resolver_with_no_request_reads_only_what_is_stored():
    # What the projection gets: it runs in a process with no business making
    # requests, and a wiki nobody has read yet simply folds on the built-ins.
    with db.session_scope() as session:
        assert wiki_namespaces.resolver(session)(DEWIKI) == ()
    wiki_namespaces.refresh(FakeSiteinfo(), DEWIKI)
    with db.session_scope() as session:
        assert wiki_namespaces.resolver(session)(DEWIKI) == ("User", "Benutzer")


def test_an_unnamed_wiki_is_not_looked_up():
    wiki = FakeSiteinfo()
    with db.session_scope() as session:
        assert wiki_namespaces.resolver(session, wiki)("") == ()
    assert wiki.asked == []


def test_junk_in_the_stored_column_does_not_reach_the_fold():
    # The column is JSON written by whatever version of this code last ran. A
    # spelling that is not a string would reach `re.escape` and raise inside a
    # census that has nothing to do with namespaces.
    with db.session_scope() as session:
        session.add(WikiNamespaceSpelling(wiki=DEWIKI, spellings=["Benutzer", None, 7, "  "], read_at=utcnow()))
    with db.session_scope() as session:
        assert wiki_namespaces.resolver(session)(DEWIKI) == ("Benutzer", "7")


def test_a_wiki_declaring_absurdly_many_names_is_bounded():
    names = tuple(f"N{index}" for index in range(wiki_namespaces.MAX_SPELLINGS + 20))
    wiki_namespaces.refresh(FakeSiteinfo(names), DEWIKI)
    assert len(row()["spellings"]) == wiki_namespaces.MAX_SPELLINGS
