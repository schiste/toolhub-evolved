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


def test_an_origin_carries_the_name_on_the_first_revision():
    rows = ((b"Hiob/monobook.js", b"20090701235434", b"Hiob"), ("A/b.js", 20040528131424, "Dr Brains"))
    assert wiki_replica.read_page_origins(rows) == {
        "Hiob/monobook.js": wiki_replica.PageOrigin("20090701235434", "Hiob"),
        "A/b.js": wiki_replica.PageOrigin("20040528131424", "Dr Brains"),
    }


def test_a_suppressed_author_keeps_the_date_and_loses_only_the_name():
    """The edit happened, so the page has a birthday; the wiki withholds the name."""
    found = wiki_replica.read_page_origins(((b"A/b.js", b"20040528131424", b""),))
    assert found == {"A/b.js": wiki_replica.PageOrigin("20040528131424", "")}


def test_an_origin_with_no_timestamp_is_left_out_even_when_it_has_a_name():
    """A row this cannot date is a row it can say nothing about."""
    assert wiki_replica.read_page_origins(((b"A/b.js", None, b"Hiob"),)) == {}


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


def test_creation_origins_are_asked_for_user_space_scripts_only():
    seen, closed, targets = [], [], []
    found = wiki_replica.creation_origins_for(
        "frwiki",
        user=wiki_replica.Credentials("u", "p"),
        connect=connector(((b"Hiob/monobook.js", b"20090701235434", b"Hiob"),), seen, closed, targets),
    )
    sql, params = seen[0]
    assert params == (2, "%.js", "%.css")
    assert targets[0][1].host == "frwiki.analytics.db.svc.wikimedia.cloud"
    assert found == {"Hiob/monobook.js": wiki_replica.PageOrigin("20090701235434", "Hiob")}


def test_the_creation_query_names_the_first_revision_rather_than_aggregating_it():
    """An aggregate returns a value; only a named row can also name its author."""
    seen = []
    wiki_replica.creation_origins_for(
        "frwiki",
        user=wiki_replica.Credentials("u", "p"),
        connect=connector((), seen, [], []),
    )
    sql, _ = seen[0]
    assert "GROUP BY" not in sql
    assert "MIN(" not in sql
    assert "ORDER BY r2.rev_timestamp, r2.rev_id LIMIT 1" in sql
    assert "a.actor_name" in sql


def test_a_revision_whose_author_mediawiki_suppressed_publishes_no_name():
    """The date is still a fact; the name is one the wiki has withdrawn."""
    seen = []
    wiki_replica.creation_origins_for(
        "frwiki",
        user=wiki_replica.Credentials("u", "p"),
        connect=connector((), seen, [], []),
    )
    sql, _ = seen[0]
    assert "rev_deleted & 4 = 0" in sql


def test_gadget_creation_origins_are_asked_for_the_gadget_prefix_in_interface_space():
    seen, closed, targets = [], [], []
    found = wiki_replica.gadget_creation_origins_for(
        "frwiki",
        user=wiki_replica.Credentials("u", "p"),
        connect=connector(((b"Gadget-HotCat.js", b"20070311120000", b"Cacycle"),), seen, closed, targets),
    )
    sql, params = seen[0]
    assert params == (8, "Gadget-%")
    assert "a.actor_name" in sql
    assert targets[0][1].host == "frwiki.analytics.db.svc.wikimedia.cloud"
    assert found == {"Gadget-HotCat.js": wiki_replica.PageOrigin("20070311120000", "Cacycle")}


def test_the_gadget_query_asks_for_no_suffix_and_so_finds_every_kind_of_code_page():
    """A gadget can ship .json, and one that does must still have a date."""
    seen = []
    wiki_replica.gadget_creation_origins_for(
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
        wiki_replica.creation_origins_for("frwiki", user=wiki_replica.Credentials("u", "p"), connect=connect)
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


# --- section addressing and the pass-scoped pool ---------------------------


class PooledConnection:
    """A connection that records the databases it was switched to."""

    def __init__(self, rows, seen, closed, database, switches):
        self.rows, self.seen, self.closed = rows, seen, closed
        self.database, self.switches = database, switches

    def cursor(self):
        return FakeCursor(self.rows, self.seen)

    def select_db(self, database):
        self.database = database
        self.switches.append(database)

    def close(self):
        self.closed.append(self.database)


def pooling_connector(rows, seen, closed, opened, switches):
    def connect(user, target):
        opened.append(target.host)
        return PooledConnection(rows, seen, closed, target.database, switches)

    return connect


def test_a_wiki_with_no_section_is_still_addressed_by_its_own_alias():
    target = wiki_replica.target_for("frwiki")
    assert target == wiki_replica.Target(
        host="frwiki.analytics.db.svc.wikimedia.cloud", database="frwiki_p"
    )


def test_a_section_addresses_the_shared_instance_and_keeps_the_wikis_database():
    target = wiki_replica.target_for("frwiki", "s6")
    assert target == wiki_replica.Target(
        host="s6.analytics.db.svc.wikimedia.cloud", database="frwiki_p"
    )


def test_the_column_spelling_of_a_section_is_not_the_address_spelling():
    assert wiki_replica.section_of("s6.labsdb") == "s6"
    assert wiki_replica.section_of("s3.labsdb") == "s3"
    # A row that has already been stripped, and one that has no section at all.
    assert wiki_replica.section_of("s1") == "s1"
    assert wiki_replica.section_of("") == ""


def test_wikis_sharing_a_section_share_one_connection():
    """The whole point: 869 wikis on one instance must not be 869 connections."""
    seen, closed, opened, switches = [], [], [], []
    user = wiki_replica.Credentials(user="s1", password="p")
    connect = pooling_connector([], seen, closed, opened, switches)
    with wiki_replica.pooled(connect) as pooled:
        for dbname in ("aawiki", "abwiki", "acewiki"):
            wiki_replica.script_edit_dates_for(dbname, section="s3", user=user, connect=pooled)
    assert opened == ["s3.analytics.db.svc.wikimedia.cloud"]
    # The first wiki is served by the database the connection opened on; only
    # the wikis after it need switching to.
    assert switches == ["abwiki_p", "acewiki_p"]
    assert len(seen) == 3


def test_a_reader_closing_its_connection_does_not_close_the_pools():
    """Readers close what they open. Inside a pass that has to mean 'release'."""
    seen, closed, opened, switches = [], [], [], []
    user = wiki_replica.Credentials(user="s1", password="p")
    connect = pooling_connector([], seen, closed, opened, switches)
    with wiki_replica.pooled(connect) as pooled:
        wiki_replica.script_edit_dates_for("aawiki", section="s3", user=user, connect=pooled)
        assert closed == []
        wiki_replica.gadget_edit_dates_for("abwiki", section="s3", user=user, connect=pooled)
        assert closed == []
    assert closed == ["abwiki_p"]


def test_wikis_on_different_sections_get_different_connections():
    seen, closed, opened, switches = [], [], [], []
    user = wiki_replica.Credentials(user="s1", password="p")
    connect = pooling_connector([], seen, closed, opened, switches)
    with wiki_replica.pooled(connect) as pooled:
        wiki_replica.script_edit_dates_for("enwiki", section="s1", user=user, connect=pooled)
        wiki_replica.script_edit_dates_for("frwiki", section="s6", user=user, connect=pooled)
        wiki_replica.script_edit_dates_for("dewiki", section="s5", user=user, connect=pooled)
    assert opened == [
        "s1.analytics.db.svc.wikimedia.cloud",
        "s6.analytics.db.svc.wikimedia.cloud",
        "s5.analytics.db.svc.wikimedia.cloud",
    ]
    assert switches == []


def test_the_pool_closes_every_connection_it_opened_even_when_a_read_raises():
    closed, opened, switches = [], [], []
    user = wiki_replica.Credentials(user="s1", password="p")

    def connect(_user, target):
        opened.append(target.host)
        return PooledConnection([], [], closed, target.database, switches)

    with pytest.raises(RuntimeError), wiki_replica.pooled(connect) as pooled:
        wiki_replica.script_edit_dates_for("enwiki", section="s1", user=user, connect=pooled)
        message = "the pass gave up"
        raise RuntimeError(message)
    assert closed == ["enwiki_p"]


def test_a_connection_that_stops_giving_cursors_is_dropped_not_reused():
    """One wiki's dead connection must not be inherited by the next wiki."""
    opened, closed = [], []

    class Broken(PooledConnection):
        def cursor(self):
            message = "server has gone away"
            raise OSError(message)

    def connect(_user, target):
        opened.append(target.host)
        return (Broken if len(opened) == 1 else PooledConnection)([], [], closed, target.database, [])

    user = wiki_replica.Credentials(user="s1", password="p")
    with wiki_replica.pooled(connect) as pooled:
        with pytest.raises(OSError, match="gone away"):
            wiki_replica.script_edit_dates_for("aawiki", section="s3", user=user, connect=pooled)
        # The next wiki on the same section reconnects rather than failing for
        # a reason that has nothing to do with it.
        wiki_replica.script_edit_dates_for("abwiki", section="s3", user=user, connect=pooled)
    assert opened == ["s3.analytics.db.svc.wikimedia.cloud"] * 2


def test_without_a_section_the_pool_reuses_nothing():
    """Per-wiki aliases are distinct hosts, so pooling them is a no-op, not a bug."""
    seen, closed, opened, switches = [], [], [], []
    user = wiki_replica.Credentials(user="s1", password="p")
    connect = pooling_connector([], seen, closed, opened, switches)
    with wiki_replica.pooled(connect) as pooled:
        wiki_replica.script_edit_dates_for("aawiki", user=user, connect=pooled)
        wiki_replica.script_edit_dates_for("abwiki", user=user, connect=pooled)
    assert opened == [
        "aawiki.analytics.db.svc.wikimedia.cloud",
        "abwiki.analytics.db.svc.wikimedia.cloud",
    ]


# --- the roster ------------------------------------------------------------


def test_the_roster_reads_identity_and_address_out_of_one_row():
    rows = ((b"frwiki", b"https://fr.wikipedia.org", b"wikipedia", b"fr", b"s6.labsdb", 0),)
    (entry,) = wiki_replica.read_roster(rows)
    assert entry == wiki_replica.WikiRow(
        wiki="fr.wikipedia.org",
        dbname="frwiki",
        section="s6",
        family="wikipedia",
        lang="fr",
        closed=False,
    )


def test_a_closed_wiki_is_on_the_roster_and_says_so():
    """Closed wikis are readable and their scripts are real; they just never change."""
    rows = ((b"aawiki", b"https://aa.wikipedia.org", b"wikipedia", b"aa", b"s3.labsdb", 1),)
    (entry,) = wiki_replica.read_roster(rows)
    assert (entry.wiki, entry.closed) == ("aa.wikipedia.org", True)


def test_the_flags_survive_the_decimals_the_driver_returns():
    """`is_closed` comes back as Decimal('1'), which is truthy either way -- and
    Decimal('0'), which is falsy as a number and truthy as an object."""
    from decimal import Decimal

    rows = (
        (b"a", b"https://a.example", b"f", b"x", b"s3.labsdb", Decimal("0")),
        (b"b", b"https://b.example", b"f", b"x", b"s3.labsdb", Decimal("1")),
    )
    assert [entry.closed for entry in wiki_replica.read_roster(rows)] == [False, True]


def test_a_row_with_no_database_or_no_host_is_not_a_wiki_that_can_be_read():
    rows = (
        (b"", b"https://nowhere.example", b"f", b"x", b"s3.labsdb", 0),
        (b"orphan", b"", b"f", b"x", b"s3.labsdb", 0),
        (b"good", b"https://good.example", b"f", b"x", b"s3.labsdb", 0),
    )
    assert [entry.dbname for entry in wiki_replica.read_roster(rows)] == ["good"]


def test_a_wiki_with_no_section_is_kept_and_read_singly():
    """Not knowing where a wiki lives is a reason to address it the long way,
    not a reason to drop it from the roster."""
    rows = ((b"oddwiki", b"https://odd.example", b"f", b"x", b"", 0),)
    (entry,) = wiki_replica.read_roster(rows)
    assert entry.section == ""
    assert wiki_replica.target_for(entry.dbname, entry.section).host.startswith("oddwiki.")


def test_the_roster_is_one_read_of_meta_and_nothing_per_wiki():
    seen, closed, targets = [], [], []
    rows = ((b"frwiki", b"https://fr.wikipedia.org", b"wikipedia", b"fr", b"s6.labsdb", 0),)
    user = wiki_replica.Credentials(user="s1", password="p")
    entries = wiki_replica.roster_for(user=user, connect=connector(rows, seen, closed, targets))
    assert [entry.wiki for entry in entries] == ["fr.wikipedia.org"]
    assert [target.database for _user, target in targets] == ["meta_p"]
    assert [params for _sql, params in seen] == [()]


# --- resolving where each wiki is read ------------------------------------


@pytest.fixture
def _has_credentials(monkeypatch):
    monkeypatch.setattr(wiki_replica, "credentials", lambda: wiki_replica.Credentials(user="s1", password="p"))


@pytest.mark.usefixtures("_has_credentials")
def test_a_caller_that_already_knows_the_addresses_never_asks_meta():
    """The registry stores this. A scheduled pass over a thousand wikis must not
    reopen `meta_p` to relearn it."""
    opened = []

    def connect(_user, target):
        opened.append(target.database)
        return FakeConnection([], [], [])

    known = {"fr.wikipedia.org": wiki_replica.Address(dbname="frwiki", section="s6")}
    user, found = wiki_replica.resolve(["fr.wikipedia.org"], connect=connect, known=known)
    assert user is not None
    assert found == known
    assert opened == []


@pytest.mark.usefixtures("_has_credentials")
def test_a_wiki_the_caller_does_not_know_is_looked_up():
    rows = ((b"metawiki", b"https://meta.wikimedia.org"),)
    seen = []
    known = {"fr.wikipedia.org": wiki_replica.Address(dbname="frwiki", section="s6")}
    _user, found = wiki_replica.resolve(
        ["fr.wikipedia.org", "meta.wikimedia.org"],
        connect=connector(rows, seen, []),
        known=known,
    )
    assert found["meta.wikimedia.org"] == wiki_replica.Address(dbname="metawiki", section="")
    # Only the wiki that was missing was asked about.
    assert seen[0][1] == ("https://meta.wikimedia.org",)


@pytest.mark.usefixtures("_has_credentials")
def test_a_meta_that_will_not_answer_leaves_the_caller_what_it_already_knew():
    """A scheduled pass supplies every address, so an unreachable meta_p must
    not cost it the wikis it could have covered without one."""

    def refuse(_user, _target):
        message = "connection refused"
        raise OSError(message)

    known = {"fr.wikipedia.org": wiki_replica.Address(dbname="frwiki", section="s6")}
    user, found = wiki_replica.resolve(["fr.wikipedia.org", "new.example"], connect=refuse, known=known)
    assert user is not None
    assert found == known


def test_no_credentials_resolves_nothing(monkeypatch):
    monkeypatch.setattr(wiki_replica, "credentials", lambda: None)
    known = {"fr.wikipedia.org": wiki_replica.Address(dbname="frwiki")}
    assert wiki_replica.resolve(["fr.wikipedia.org"], known=known) == (None, {})


@pytest.mark.usefixtures("_has_credentials")
def test_an_address_with_no_database_is_not_an_address():
    """A registry row written before its wiki was resolvable must not be
    mistaken for a known one and skip the lookup."""
    rows = ((b"frwiki", b"https://fr.wikipedia.org"),)
    known = {"fr.wikipedia.org": wiki_replica.Address(dbname="", section="s6")}
    _user, found = wiki_replica.resolve(["fr.wikipedia.org"], connect=connector(rows, [], []), known=known)
    assert found["fr.wikipedia.org"].dbname == "frwiki"
