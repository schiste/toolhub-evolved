# SPDX-License-Identifier: GPL-3.0-or-later
"""The Wiki Replica reader: credentials, addressing, and reading rows back.

No test here reaches a replica. The connection is injected, so what is tested
is everything around it -- which is where the mistakes are, because the replica
speaks bytes, spells titles differently from the census, and is absent entirely
outside Toolforge.
"""

from datetime import datetime

import pytest

from backend import wiki_replica

CNF = "[client]\nuser='s55555'\npassword='sekrit'\n"


class FakeCursor:
    """Records the statement it was given and replays canned rows."""

    def __init__(self, rows, seen):
        self.rows, self.seen = rows, seen

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.seen.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    """One connection that must be closed exactly once."""

    def __init__(self, rows, seen, closed):
        self.rows, self.seen, self.closed = rows, seen, closed

    def cursor(self):
        return FakeCursor(self.rows, self.seen)

    def close(self):
        self.closed.append(True)


def connector(rows, seen, closed, targets=None):
    def connect(user, target):
        if targets is not None:
            targets.append((user, target))
        return FakeConnection(rows, seen, closed)

    return connect


# --- credentials -----------------------------------------------------------


def test_credentials_are_read_with_the_quotes_toolforge_writes_stripped():
    parsed = wiki_replica.parse_credentials(CNF)
    assert (parsed.user, parsed.password) == ("s55555", "sekrit")


def test_a_file_that_is_not_a_replica_config_is_not_credentials():
    assert wiki_replica.parse_credentials("[other]\nuser='x'\n") is None


def test_an_unparseable_file_is_not_credentials():
    assert wiki_replica.parse_credentials("this is not ini = = =\n[[[") is None


def test_a_config_missing_the_password_is_not_credentials():
    assert wiki_replica.parse_credentials("[client]\nuser='s1'\n") is None


def test_a_config_missing_the_user_is_not_credentials():
    assert wiki_replica.parse_credentials("[client]\npassword='p'\n") is None


def test_credentials_come_from_the_configured_path(tmp_path, monkeypatch):
    path = tmp_path / "replica.my.cnf"
    path.write_text(CNF, encoding="utf-8")
    monkeypatch.setenv(wiki_replica.CONFIG_PATH_ENV, str(path))
    assert wiki_replica.credentials().user == "s55555"
    assert wiki_replica.available() is True


def test_a_missing_credentials_file_is_absence_not_an_error(tmp_path, monkeypatch):
    """Off Toolforge there is no replica, and every caller has to cope with that."""
    monkeypatch.setenv(wiki_replica.CONFIG_PATH_ENV, str(tmp_path / "absent.cnf"))
    assert wiki_replica.credentials() is None
    assert wiki_replica.available() is False


def test_the_default_path_is_used_when_nothing_is_configured(monkeypatch):
    monkeypatch.delenv(wiki_replica.CONFIG_PATH_ENV, raising=False)
    assert wiki_replica.config_path().name == "replica.my.cnf"


# --- addressing ------------------------------------------------------------


def test_a_wiki_is_reached_on_its_analytics_replica():
    target = wiki_replica.target_for("frwiki")
    assert target.host == "frwiki.analytics.db.svc.wikimedia.cloud"
    assert target.database == "frwiki_p"


def test_the_wiki_host_is_looked_up_by_its_canonical_https_url():
    assert wiki_replica.url_for("fr.wikipedia.org") == "https://fr.wikipedia.org"


# --- titles ----------------------------------------------------------------


def test_a_census_title_is_reduced_to_the_form_the_replica_stores():
    """The replica drops the namespace and writes underscores for spaces."""
    assert wiki_replica.normalize_title("Utilisateur:Tom Smith/monobook.js") == "Tom_Smith/monobook.js"


def test_a_title_without_a_namespace_prefix_survives_normalization():
    assert wiki_replica.normalize_title("Hiob/monobook.js") == "Hiob/monobook.js"


# --- reading rows ----------------------------------------------------------


def test_wiki_hosts_map_to_their_database_names():
    rows = ((b"frwiki", b"https://fr.wikipedia.org"), ("metawiki", "https://meta.wikimedia.org"))
    assert wiki_replica.read_dbnames(rows) == {
        "fr.wikipedia.org": "frwiki",
        "meta.wikimedia.org": "metawiki",
    }


def test_a_plain_http_wiki_url_maps_too():
    assert wiki_replica.read_dbnames((("w", "http://old.example.org"),)) == {"old.example.org": "w"}


def test_a_row_missing_either_half_is_skipped():
    assert wiki_replica.read_dbnames(((None, "https://x.org"), ("y", None))) == {}


def test_creation_dates_are_read_as_text_whatever_the_driver_returns():
    rows = ((b"Hiob/monobook.js", b"20090701235434"), ("A/b.js", 20040528131424))
    assert wiki_replica.read_page_stamps(rows) == {
        "Hiob/monobook.js": "20090701235434",
        "A/b.js": "20040528131424",
    }


def test_a_page_with_no_surviving_revision_is_left_out():
    assert wiki_replica.read_page_stamps(((b"A/b.js", None),)) == {}


# --- the queries themselves ------------------------------------------------


def test_asking_for_no_wikis_asks_the_replica_nothing():
    """A caller with an empty wiki list must not open a connection to find that out."""
    def refuse(user, target):  # pragma: no cover - must never run
        raise AssertionError

    assert wiki_replica.dbnames_for([], user=wiki_replica.Credentials("u", "p"), connect=refuse) == {}


def test_the_dbname_lookup_asks_meta_with_one_placeholder_per_wiki():
    seen, closed, targets = [], [], []
    user = wiki_replica.Credentials("u", "p")
    found = wiki_replica.dbnames_for(
        ["fr.wikipedia.org", "meta.wikimedia.org"],
        user=user,
        connect=connector(((b"frwiki", b"https://fr.wikipedia.org"),), seen, closed, targets),
    )
    sql, params = seen[0]
    assert sql.count("%s") == 2
    assert params == ("https://fr.wikipedia.org", "https://meta.wikimedia.org")
    assert targets[0][1].database == "meta_p"
    assert found == {"fr.wikipedia.org": "frwiki"}


def test_creation_dates_are_asked_for_user_space_scripts_only():
    seen, closed, targets = [], [], []
    found = wiki_replica.creation_dates_for(
        "frwiki",
        user=wiki_replica.Credentials("u", "p"),
        connect=connector(((b"Hiob/monobook.js", b"20090701235434"),), seen, closed, targets),
    )
    sql, params = seen[0]
    assert params == (2, "%.js", "%.css")
    assert "GROUP BY p.page_id" in sql
    assert targets[0][1].host == "frwiki.analytics.db.svc.wikimedia.cloud"
    assert found == {"Hiob/monobook.js": "20090701235434"}


def test_gadget_creation_dates_are_asked_for_the_gadget_prefix_in_interface_space():
    seen, closed, targets = [], [], []
    found = wiki_replica.gadget_creation_dates_for(
        "frwiki",
        user=wiki_replica.Credentials("u", "p"),
        connect=connector(((b"Gadget-HotCat.js", b"20070311120000"),), seen, closed, targets),
    )
    sql, params = seen[0]
    assert params == (8, "Gadget-%")
    assert "GROUP BY p.page_id" in sql
    assert targets[0][1].host == "frwiki.analytics.db.svc.wikimedia.cloud"
    assert found == {"Gadget-HotCat.js": "20070311120000"}


def test_the_gadget_query_asks_for_no_suffix_and_so_finds_every_kind_of_code_page():
    """A gadget can ship .json, and one that does must still have a date."""
    seen = []
    wiki_replica.gadget_creation_dates_for(
        "frwiki",
        user=wiki_replica.Credentials("u", "p"),
        connect=connector((), seen, [], []),
    )
    sql, _ = seen[0]
    assert ".js" not in sql
    assert sql.count("%s") == 2


# --- rendering a stored timestamp ------------------------------------------


def test_a_mediawiki_timestamp_becomes_an_iso_instant():
    assert wiki_replica.iso_timestamp("20040429080822") == "2004-04-29T08:08:22Z"


def test_a_rendered_timestamp_is_what_fromisoformat_reads_back():
    """Every consumer of a published creation date parses it this way."""
    assert datetime.fromisoformat(wiki_replica.iso_timestamp("20040429080822")) == datetime.fromisoformat(
        "2004-04-29T08:08:22+00:00"
    )


@pytest.mark.parametrize("stamp", ["", "2004", "20040429080822000", "2004-04-29", "not a stamp!!", "2004042908082x"])
def test_anything_that_is_not_a_mediawiki_timestamp_renders_as_nothing(stamp):
    """A blank is the ordinary answer for an undated page; a guess never is."""
    assert wiki_replica.iso_timestamp(stamp) == ""


def test_surrounding_whitespace_does_not_stop_a_stamp_being_read():
    assert wiki_replica.iso_timestamp(" 20040429080822 ") == "2004-04-29T08:08:22Z"


def test_the_connection_is_closed_even_when_the_query_fails():
    """A replica that errors mid-read must not leak the connection."""
    closed = []

    class Exploding(FakeConnection):
        def cursor(self):
            raise RuntimeError("replica went away")

    def connect(user, target):
        return Exploding((), [], closed)

    try:
        wiki_replica.creation_dates_for("frwiki", user=wiki_replica.Credentials("u", "p"), connect=connect)
    except RuntimeError:
        pass
    assert closed == [True]


# --- enumeration -----------------------------------------------------------


def test_every_script_page_comes_back_paired_with_its_content_model():
    rows = ((b"javascript", b"Tom_Smith/monobook.js", b"41"), (b"css", b"Ada/vector.css", b"7"))
    assert wiki_replica.read_page_titles(rows) == (
        ("javascript", "Tom_Smith/monobook.js", "41"),
        ("css", "Ada/vector.css", "7"),
    )


def test_enumeration_keeps_the_order_the_replica_returned():
    rows = ((b"javascript", b"Zeta/z.js", b"1"), (b"javascript", b"Alpha/a.js", b"2"))
    titles = [title for _model, title, _revision in wiki_replica.read_page_titles(rows)]
    assert titles == ["Zeta/z.js", "Alpha/a.js"]


def test_a_row_missing_either_half_is_not_a_page():
    rows = ((b"javascript", b"", b"1"), (b"", b"Ada/vector.css", b"2"), (None, None, None))
    assert wiki_replica.read_page_titles(rows) == ()


def test_a_page_with_no_revision_id_is_still_a_page():
    # The revision id is a shortcut -- it lets a sweep skip fetching a page it
    # already holds. A row that cannot offer one has lost the shortcut, not its
    # place in the enumeration, so it comes back with an empty revision and a
    # sweep simply fetches it.
    rows = ((b"javascript", b"Ada/a.js", None), (b"javascript", b"Bo/b.js"))
    assert wiki_replica.read_page_titles(rows) == (
        ("javascript", "Ada/a.js", ""),
        ("javascript", "Bo/b.js", ""),
    )


def test_the_enumeration_reads_the_revision_id_off_the_row_it_already_had():
    # `page_latest` is a column on `page`, so carrying it costs no extra query
    # and no extra join -- and it is what makes a second sweep cheap.
    assert "p.page_latest" in wiki_replica.ENUMERATION_QUERY
    assert wiki_replica.ENUMERATION_QUERY.count("FROM") == 1


def test_enumeration_asks_for_user_space_by_content_model_in_creation_order():
    seen, closed = [], []
    wiki_replica.script_titles_for(
        "frwiki",
        user=wiki_replica.Credentials(user="s55555", password="sekrit"),
        connect=connector(((b"javascript", b"Ada/a.js"),), seen, closed),
    )
    sql, params = seen[0]
    assert params == (wiki_replica.USER_NAMESPACE, "javascript", "css")
    assert "page_namespace = %s" in sql
    assert "ORDER BY p.page_id" in sql
    assert closed == [True]


def test_enumeration_narrows_by_model_rather_than_by_suffix():
    # The whole point of reading the replica: a page holding JavaScript under a
    # name that does not end in `.js` is a script, and a suffix scan misses it.
    assert "LIKE" not in wiki_replica.ENUMERATION_QUERY
