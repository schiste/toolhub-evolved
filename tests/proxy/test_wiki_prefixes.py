"""Storing what a title's leading `X:` means on each wiki, and handing it to the fold.

The fold in `backend.userscripts` used to know three namespace spellings -- the
ones the two wikis censused first happen to use -- and no interwiki prefixes at
all. Everything here exists so that a wiki nobody had thought of gets its own
names read once and reused, and so that a wiki that cannot be reached is no
worse off than before this module.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscripts, wiki_prefixes  # noqa: E402
from backend.models import WikiTitlePrefixes, utcnow  # noqa: E402

DEWIKI = "de.wikipedia.org"


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    with application.app_context():
        yield


class FakeSiteinfo:
    """A wiki that answers siteinfo, counts how often it was asked, or refuses."""

    def __init__(self, names=("Benutzer",), *, fails=False, interwiki=(("en", "https://en.wikipedia.org/wiki/$1"),)):
        self.names = tuple(names)
        self.fails = fails
        self.interwiki = tuple(interwiki)
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
                "interwikimap": [{"prefix": prefix, "url": url} for prefix, url in self.interwiki],
            },
        }


def row(wiki=DEWIKI):
    with db.session_scope() as session:
        found = session.get(WikiTitlePrefixes, wiki)
        if found is None:
            return None
        return {
            "spellings": list(found.namespaces or []),
            "interwiki": dict(found.interwiki or {}),
            "read": found.read_at is not None,
            "checked": found.checked_at is not None,
            "status": found.status,
        }


# --- reading -----------------------------------------------------------------


def test_a_wiki_s_names_are_read_once_and_stored():
    wiki = FakeSiteinfo(("Benutzer", "Benutzerin"))
    assert wiki_prefixes.refresh(wiki, DEWIKI)["status"] == wiki_prefixes.STATUS_READ
    stored = row()
    assert stored["spellings"] == ["User", "Benutzer", "Benutzerin"]
    assert (stored["read"], stored["checked"]) == (True, True)


def test_a_wiki_that_cannot_be_reached_is_recorded_rather_than_raised():
    # One wiki refusing is not the census failing: the fold has a fallback and
    # the run has hundreds of other wikis to get through.
    assert wiki_prefixes.refresh(FakeSiteinfo(fails=True), DEWIKI)["status"] == wiki_prefixes.STATUS_UNREADABLE
    stored = row()
    assert (stored["spellings"], stored["read"], stored["checked"]) == ([], False, True)


def test_a_failed_read_keeps_the_spellings_it_already_had():
    wiki_prefixes.refresh(FakeSiteinfo(("Benutzer",)), DEWIKI)
    wiki_prefixes.refresh(FakeSiteinfo(fails=True), DEWIKI)
    stored = row()
    # Losing them would silently un-fold every dewiki title until the next
    # successful read, which is a worse outcome than never having read the wiki.
    assert stored["spellings"] == ["User", "Benutzer"]
    assert stored["status"] == wiki_prefixes.STATUS_UNREADABLE


def test_an_answer_with_no_user_namespace_is_unreadable_rather_than_empty():
    class Blank(FakeSiteinfo):
        def __call__(self, wiki, method, params):
            self.asked.append(wiki)
            return {"query": {"namespaces": {}}}

    assert wiki_prefixes.refresh(Blank(), DEWIKI)["status"] == wiki_prefixes.STATUS_UNREADABLE


# --- when to read again ------------------------------------------------------


def test_a_recent_reading_is_not_read_again():
    wiki = FakeSiteinfo()
    wiki_prefixes.refresh(wiki, DEWIKI)
    with db.session_scope() as session:
        assert wiki_prefixes.resolver(session, wiki)(DEWIKI).namespaces == ("User", "Benutzer")
    assert wiki.asked == [DEWIKI]


def test_a_reading_older_than_the_refresh_interval_is_read_again():
    wiki = FakeSiteinfo()
    wiki_prefixes.refresh(wiki, DEWIKI)
    with db.session_scope() as session:
        found = session.get(WikiTitlePrefixes, DEWIKI)
        found.read_at = utcnow() - timedelta(days=wiki_prefixes.REFRESH_AFTER_DAYS + 1)
        found.checked_at = found.read_at
    with db.session_scope() as session:
        wiki_prefixes.resolver(session, wiki)(DEWIKI)
    assert wiki.asked == [DEWIKI, DEWIKI]


def test_a_wiki_that_just_refused_is_not_asked_again_by_the_next_resolver():
    # The two clocks earn their keep here. On `read_at` alone an unreadable wiki
    # is permanently stale, so every resolver built during a run -- and there
    # are several per sweep -- spends a request rediscovering that.
    wiki = FakeSiteinfo(fails=True)
    with db.session_scope() as session:
        wiki_prefixes.resolver(session, wiki)(DEWIKI)
    with db.session_scope() as session:
        assert wiki_prefixes.resolver(session, wiki)(DEWIKI).namespaces == ()
    assert wiki.asked == [DEWIKI]


def test_a_wiki_that_refused_long_enough_ago_is_tried_again():
    wiki = FakeSiteinfo(fails=True)
    with db.session_scope() as session:
        wiki_prefixes.resolver(session, wiki)(DEWIKI)
    with db.session_scope() as session:
        found = session.get(WikiTitlePrefixes, DEWIKI)
        found.checked_at = utcnow() - timedelta(hours=wiki_prefixes.RETRY_AFTER_HOURS + 1)
    with db.session_scope() as session:
        wiki_prefixes.resolver(session, wiki)(DEWIKI)
    assert wiki.asked == [DEWIKI, DEWIKI]


# --- handing the names to the fold -------------------------------------------


def test_one_resolver_asks_about_a_wiki_once_however_often_it_is_named():
    # A sweep resolves the target namespace of every load edge on every page,
    # which is tens of thousands of lookups across a handful of wikis.
    wiki = FakeSiteinfo()
    with db.session_scope() as session:
        spellings = wiki_prefixes.resolver(session, wiki)
        assert [spellings(DEWIKI).namespaces for _ in range(50)] == [("User", "Benutzer")] * 50
    assert wiki.asked == [DEWIKI]


def test_a_resolver_with_no_request_reads_only_what_is_stored():
    # What the projection gets: it runs in a process with no business making
    # requests, and a wiki nobody has read yet simply folds on the built-ins.
    with db.session_scope() as session:
        assert wiki_prefixes.resolver(session)(DEWIKI).namespaces == ()
    wiki_prefixes.refresh(FakeSiteinfo(), DEWIKI)
    with db.session_scope() as session:
        assert wiki_prefixes.resolver(session)(DEWIKI).namespaces == ("User", "Benutzer")


def test_an_unnamed_wiki_is_not_looked_up():
    wiki = FakeSiteinfo()
    with db.session_scope() as session:
        assert wiki_prefixes.resolver(session, wiki)("") == userscripts.WikiPrefixes()
    assert wiki.asked == []


def test_junk_in_the_stored_column_does_not_reach_the_fold():
    # The column is JSON written by whatever version of this code last ran. A
    # spelling that is not a string would reach `re.escape` and raise inside a
    # census that has nothing to do with namespaces.
    with db.session_scope() as session:
        session.add(WikiTitlePrefixes(wiki=DEWIKI, namespaces=["Benutzer", None, 7, "  "], read_at=utcnow()))
    with db.session_scope() as session:
        assert wiki_prefixes.resolver(session)(DEWIKI).namespaces == ("Benutzer", "7")


def test_a_wiki_declaring_absurdly_many_names_is_bounded():
    names = tuple(f"N{index}" for index in range(wiki_prefixes.MAX_SPELLINGS + 20))
    wiki_prefixes.refresh(FakeSiteinfo(names), DEWIKI)
    assert len(row()["spellings"]) == wiki_prefixes.MAX_SPELLINGS


# --- interwiki ---------------------------------------------------------------


def test_a_wiki_s_interwiki_map_is_stored_as_prefix_to_host():
    # Stored as the host alone rather than the URL template: the census keys
    # everything on the wiki's host, and `$1` is the one part of the template
    # nothing downstream ever fills in.
    wiki = FakeSiteinfo(interwiki=(("en", "https://en.wikipedia.org/wiki/$1"), ("w", "//en.wikipedia.org/wiki/$1")))
    wiki_prefixes.refresh(wiki, DEWIKI)
    assert row()["interwiki"] == {"en": "en.wikipedia.org", "w": "en.wikipedia.org"}


def test_a_prefix_that_is_also_a_namespace_name_is_not_stored_as_an_interwiki():
    # `wikipedia:` is both on enwiki, and MediaWiki resolves the namespace
    # first. Following it would move thousands of `Wikipedia:` titles onto a
    # wiki they were never on -- and the metric would look like it improved.
    wiki = FakeSiteinfo(("Benutzer",), interwiki=(("benutzer", "https://elsewhere.example/wiki/$1"),))
    wiki_prefixes.refresh(wiki, DEWIKI)
    assert row()["interwiki"] == {}


def test_the_stored_prefixes_reach_the_fold_through_the_resolver():
    wiki = FakeSiteinfo()
    with db.session_scope() as session:
        found = wiki_prefixes.resolver(session, wiki)(DEWIKI)
    assert found.namespaces == ("User", "Benutzer")
    assert found.interwiki == {"en": "en.wikipedia.org"}


def test_junk_in_the_interwiki_column_does_not_reach_the_peel():
    with db.session_scope() as session:
        session.add(
            WikiTitlePrefixes(
                wiki=DEWIKI,
                namespaces=["Benutzer"],
                interwiki={"EN": " en.wikipedia.org ", "": "nowhere", "x": None},
                read_at=utcnow(),
            ),
        )
    with db.session_scope() as session:
        # Casefolded on the way out too: the peel looks up a casefolded prefix
        # read off a title, and a row written before that was true would
        # otherwise silently never match.
        assert wiki_prefixes.resolver(session)(DEWIKI).interwiki == {"en": "en.wikipedia.org"}


# --- reading rows an older version of this code wrote --------------------


def _store(wiki=DEWIKI, **fields):
    with db.session_scope() as session:
        session.add(WikiTitlePrefixes(wiki=wiki, **fields))


def test_a_row_whose_json_is_not_the_shape_this_code_writes_is_read_as_nothing():
    # The columns are JSON written by an earlier version of this module as much
    # as by this one. A spelling that is not a string reaches `re.escape` and
    # raises inside a census that has nothing to do with namespaces.
    _store(namespaces={"User": True}, interwiki=["en"], status=wiki_prefixes.STATUS_READ, read_at=utcnow())

    with db.session_scope() as session:
        prefixes = wiki_prefixes.stored_prefixes(session, DEWIKI)

    assert prefixes.namespaces == ()
    assert prefixes.interwiki == {}


def test_a_wiki_that_has_never_been_asked_has_no_prefixes_and_is_stale():
    with db.session_scope() as session:
        assert wiki_prefixes.stored_prefixes(session, DEWIKI) == userscripts.WikiPrefixes()
    assert wiki_prefixes.is_stale(None) is True


def test_a_row_that_records_neither_a_reading_nor_an_attempt_is_asked_again():
    # Both clocks unset: the row says nothing about when this wiki was last
    # tried, so treating it as fresh would pin it out of every future pass.
    assert wiki_prefixes.is_stale(WikiTitlePrefixes(wiki=DEWIKI, read_at=None, checked_at=None)) is True
