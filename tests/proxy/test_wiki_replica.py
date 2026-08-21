# SPDX-License-Identifier: GPL-3.0-or-later
"""The Wiki Replica reader: credentials, addressing, and reading rows back.

No test here reaches a replica. The connection is injected, so what is tested
is everything around it -- which is where the mistakes are, because the replica
speaks bytes, spells titles differently from the census, and is absent entirely
outside Toolforge.
"""

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
    assert wiki_replica.normalize_title("Utilisateur:Tom Blaireau/monobook.js") == "Tom_Blaireau/monobook.js"


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
    assert wiki_replica.read_creation_dates(rows) == {
        "Hiob/monobook.js": "20090701235434",
        "A/b.js": "20040528131424",
    }


def test_a_page_with_no_surviving_revision_is_left_out():
    assert wiki_replica.read_creation_dates(((b"A/b.js", None),)) == {}


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
