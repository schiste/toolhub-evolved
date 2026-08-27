# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading page facts from the Wiki Replicas, for questions the API prices badly.

The Action API is the right way to ask a wiki about a page, and the census uses
it for everything it reads. It is the wrong way to ask about *every* page at
once, because some questions cannot be batched. "When was this page created"
is one of them: it is `rvdir=newer&rvlimit=1`, and the API refuses that
combination for more than one title at a time -- `invalidparammix`, by design,
not by quota. One request per page, for a corpus of ten thousand pages, is an
hour and a half of requests to learn something the wiki already has indexed.

The Wiki Replicas answer the same question as one `GROUP BY`. Measured on
fr.wikipedia: 14,431 user-space script pages with their creation dates in about
a second, complete back to 2004. Toolforge tools are given replica credentials
precisely so they do not have to spend the API's budget on this.

Enumeration is the second such question, and the sharper one. "Which pages on
this wiki are scripts" is `contentmodel:javascript` to the search index, which
refuses an offset past 10,000 and whose prefix clauses do not compose -- so on
Meta it can name ten thousand of 25,354 pages and cannot be partitioned into
walkable pieces. The replica answers it exactly, in one indexed read, with no
cap and in creation order.

Read-only and best-effort, deliberately. The replicas are reachable only from
inside Toolforge, so every caller must work without them -- `available()` says
whether to try, and a failed read is a missing answer rather than a failed job.
Nothing here writes, and nothing here is on a request path.

Only page metadata is read: a title, a timestamp, and the name signed to the
page's first revision. That last one is attribution rather than a private fact
-- it is the first line of the page history every reader can already see, and
for a gadget it is the only evidence a wiki offers about who wrote it. A
revision whose author MediaWiki has suppressed contributes no name. Edit
comments are still read by nothing here.
"""

from __future__ import annotations

import configparser
import os
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

#: Where Toolforge writes a tool's replica credentials.
DEFAULT_CONFIG_PATH = "~/replica.my.cnf"
#: Overrides the above, for a deployment that keeps the file elsewhere.
CONFIG_PATH_ENV = "TOOLHUB_REPLICA_CONFIG"

# The analytics replicas, not the web ones. These lag further behind but are the
# ones sized for a GROUP BY over a whole table; the web replicas exist to keep
# interactive tools responsive and should not be asked to do this.
HOST_SUFFIX = ".analytics.db.svc.wikimedia.cloud"
#: Holds the authoritative url-to-database map for every Wikimedia wiki.
META_DB = "meta"

#: User space. The census reads only this namespace, and so does this.
USER_NAMESPACE = 2

#: Where a wiki keeps its interface pages, and so its gadget code. A gadget is
#: declared on one page and implemented on others; the others live here.
MEDIAWIKI_NAMESPACE = 8
#: What every gadget code page's title begins with, once the namespace is off.
#: `MediaWiki:Gadget-HotCat.js` is stored as `Gadget-HotCat.js`, so this is both
#: the LIKE pattern's prefix and the key the declaration's file names are
#: matched under.
GADGET_TITLE_PREFIX = "Gadget-"

# `page_title` is stored without its namespace prefix and with underscores for
# spaces. Stored census titles are full, localized and spaced
# (`Utilisateur:Tom Smith/monobook.js`), so the two are matched on the part
# after the first colon with spaces folded to underscores. Doing it this way
# means never needing to know what a wiki calls namespace 2.
TITLE_SEPARATOR = ":"


@dataclass(frozen=True)
class Credentials:
    """A replica username and password, as Toolforge writes them."""

    user: str
    password: str


@dataclass(frozen=True)
class Target:
    """One replica database, and the host that serves it."""

    host: str
    database: str


if TYPE_CHECKING:
    #: Opens one read-only replica connection to a target.
    Connect = Callable[[Credentials, Target], Any]


def target_for(dbname: str, section: str = "") -> Target:
    """Return where to reach one wiki's replica, by its database name.

    Without a section this is the per-wiki alias, which is the right address for
    a tool that reads one or two wikis: it needs to know nothing but the name.

    With one it is the shared instance that wiki lives on, and every wiki on that
    instance resolves to the same host. That is what lets a pass covering
    hundreds of wikis open one connection instead of hundreds, which the
    replicas' own documentation asks for by name -- section addressing is
    discouraged generally and excepted for "heavily crosswiki tools which would
    otherwise open hundreds of database connections". Eight instances serve every
    Wikimedia wiki, and one of them serves 869 of them, so the difference for a
    full pass is three orders of magnitude of connection churn.
    """
    host = section or dbname
    return Target(host=f"{host}{HOST_SUFFIX}", database=f"{dbname}_p")


def config_path() -> Path:
    """Return the configured credentials path, expanded."""
    return Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH)).expanduser()


def parse_credentials(text: str) -> Credentials | None:
    """Read a `replica.my.cnf`, or return None if it is not one.

    Toolforge quotes both values. `configparser` keeps the quotes, so they are
    stripped here rather than surviving into a connection attempt that would
    fail with an authentication error and no hint of why.
    """
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    if not parser.has_section("client"):
        return None
    user = parser["client"].get("user", "").strip().strip("'\"")
    password = parser["client"].get("password", "").strip().strip("'\"")
    if not user or not password:
        return None
    return Credentials(user=user, password=password)


def credentials() -> Credentials | None:
    """Read this tool's replica credentials, or None when there are none."""
    path = config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_credentials(text)


def available() -> bool:
    """Whether replica reads are worth attempting from this process."""
    return credentials() is not None


DBNAME_QUERY = "SELECT dbname, url FROM wiki WHERE url IN ({placeholders})"

# The earliest surviving revision of each page, located rather than aggregated.
# `MIN(rev_timestamp)` answered when a page was created and could never say who
# created it, because an aggregate returns a value and not the row it came from.
# Naming that row by id is what lets its author ride along, and it is not the
# more expensive question: the correlated lookup walks the `(rev_page,
# rev_timestamp)` index one dive per page instead of folding every revision the
# page ever had. Measured on fr.wikipedia's user space, both forms return the
# same 14,433 pages inside the same second.
#
# Revisions removed by deletion live in `archive` and are deliberately not
# consulted: a page whose first edits were deleted reads as very slightly newer
# than it was, and is credited to the oldest author who remains, which is the
# honest answer from what the wiki still shows. Reading `archive` would mean
# reading rows an administrator chose to withdraw.
#
# `rev_deleted & 4` is MediaWiki's "username suppressed" bit. Such a revision
# still dates the page -- the edit happened -- but contributes no name, which
# reaches the catalogue as a tool with a creation date and no author.
CREATION_QUERY = (
    "SELECT p.page_title, r.rev_timestamp, IF(r.rev_deleted & 4 = 0, a.actor_name, '') "
    "FROM page p "
    "JOIN revision r ON r.rev_id = ("
    "SELECT r2.rev_id FROM revision r2 WHERE r2.rev_page = p.page_id "
    "ORDER BY r2.rev_timestamp, r2.rev_id LIMIT 1) "
    "LEFT JOIN actor a ON a.actor_id = r.rev_actor "
    "WHERE p.page_namespace = %s AND (p.page_title LIKE %s OR p.page_title LIKE %s)"
)
#: Suffixes the creation query narrows by. Content model is what decides whether
#: a page is a script -- `ENUMERATION_QUERY` below asks for it directly -- but
#: dates are stamped onto whatever is already stored, and the watch that stores
#: pages between sweeps recognises them by suffix because recent changes cannot
#: be filtered by model. Narrowing here by the wider of the two rules costs one
#: predicate and means a page the watch found is never left without a date.
TITLE_PATTERNS = ("%.js", "%.css")

#: The same question asked of gadget code, which needs no suffix filter: every
#: page under `Gadget-` is one gadget's implementation whatever it is called,
#: and a wiki has of the order of a hundred of them rather than tens of
#: thousands. `MediaWiki:Gadgets-definition` itself does not match the prefix --
#: it is `Gadgets-definition`, plural -- which is what we want: the date wanted
#: is when a gadget's code first existed, not when the wiki's list of gadgets
#: did.
GADGET_CREATION_QUERY = (
    "SELECT p.page_title, r.rev_timestamp, IF(r.rev_deleted & 4 = 0, a.actor_name, '') "
    "FROM page p "
    "JOIN revision r ON r.rev_id = ("
    "SELECT r2.rev_id FROM revision r2 WHERE r2.rev_page = p.page_id "
    "ORDER BY r2.rev_timestamp, r2.rev_id LIMIT 1) "
    "LEFT JOIN actor a ON a.actor_id = r.rev_actor "
    "WHERE p.page_namespace = %s AND p.page_title LIKE %s"
)

# The other end of the same history: when each page was last edited. Joined on
# `page_latest` rather than aggregated with MAX(rev_timestamp), which the two
# queries above have to do because there is no `page_first`. `page_latest` is
# the current revision's id, so this is one primary-key lookup per page instead
# of a scan of its whole history -- on a page edited ten thousand times the
# difference is the entire cost of the query, and the answer is the same.
#
# A "last edit" and MediaWiki's own `page_touched` are not the same thing.
# `page_touched` also moves when a template the page includes changes, or
# when a null edit refreshes the parser cache, and a catalogue that published
# it would report tools as freshly updated on days nobody touched their code.
# The revision's timestamp is the date somebody actually changed the source.
SCRIPT_EDIT_QUERY = (
    "SELECT p.page_title, r.rev_timestamp "
    "FROM page p JOIN revision r ON r.rev_id = p.page_latest "
    "WHERE p.page_namespace = %s AND (p.page_title LIKE %s OR p.page_title LIKE %s)"
)

#: The same question asked of gadget code, narrowed the way
#: `GADGET_CREATION_QUERY` is and for the same reasons.
GADGET_EDIT_QUERY = (
    "SELECT p.page_title, r.rev_timestamp "
    "FROM page p JOIN revision r ON r.rev_id = p.page_latest "
    "WHERE p.page_namespace = %s AND p.page_title LIKE %s"
)

#: Content models the census treats as scripts. Namespace-2 pages always record
#: an explicit model -- measured on 2026-08-22 across metawiki, frwiki and
#: enwiki, not one row leaves `page_content_model` NULL -- so matching on it is
#: exact rather than a filter over a suffix guess. It finds the twenty to sixty
#: pages per wiki that hold JavaScript under a name not ending in `.js`, and
#: skips the wikitext pages that do end in one.
SCRIPT_MODELS = ("javascript", "css")

# Ordered by page id, which is creation order for free: ids are handed out in
# creation sequence and never reused. The census records a title's position in
# this sequence as its discovery rank, and the directory reads that as creation
# order wherever no real timestamp has been stamped on yet.
#
# No LIMIT and no paging. This is the query the search index cannot express --
# CirrusSearch refuses an offset past 10,000 and its prefix clauses do not
# compose, so on a wiki the size of Meta it can name a prefix of the truth and
# cannot be made to prove it named the rest.
#
# `page_latest` is the current revision id, and it rides along free: it is a
# column on the row this query already reads. Carrying it is what lets a sweep
# decide a page is unchanged *before* asking the API for its body -- the fetch
# is the entire cost of a sweep, and without this a wiki's second sweep costs
# exactly as much as its first to discover that almost nothing moved.
ENUMERATION_QUERY = (
    "SELECT p.page_content_model, p.page_title, p.page_latest "
    "FROM page p "
    "WHERE p.page_namespace = %s AND p.page_content_model IN (%s, %s) "
    "ORDER BY p.page_id"
)


def url_for(wiki: str) -> str:
    """Return the canonical https origin `meta_p` records for a wiki host."""
    return f"https://{wiki}"


def normalize_title(title: str) -> str:
    """Reduce a census title to the form `page_title` uses.

    Drops the namespace prefix and folds spaces to underscores, so
    `Utilisateur:Tom Smith/monobook.js` and the replica's
    `Tom_Smith/monobook.js` are the same key.
    """
    _, separator, rest = title.partition(TITLE_SEPARATOR)
    return (rest if separator else title).replace(" ", "_")


def _decoded(value: object) -> str:
    """Return a replica column as text, whatever the driver hands back."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value is None else str(value)


def read_dbnames(rows: Iterable[Sequence[Any]]) -> dict[str, str]:
    """Map each wiki host to its database name, from `meta_p.wiki` rows."""
    found: dict[str, str] = {}
    for row in rows:
        dbname, url = _decoded(row[0]), _decoded(row[1])
        host = url.removeprefix("https://").removeprefix("http://")
        if dbname and host:
            found[host] = dbname
    return found


#: Every readable Wikimedia wiki, with what it takes to address one. `meta_p`
#: is the roster rather than a list this repository keeps: it is maintained by
#: the people who create and close wikis, it names the database and the instance
#: for each, and -- the part a hand-kept list gets wrong -- it already omits the
#: wikis with no public replica at all, so what it returns is exactly the set
#: that can be read.
ROSTER_QUERY = "SELECT dbname, url, family, lang, `slice`, is_closed FROM wiki"

#: What `meta_p.wiki.slice` appends to the section name. The column says
#: `s6.labsdb` where an address wants `s6`, and the suffix is the name of a
#: service that has since been renamed -- so it is stripped rather than carried.
SECTION_SUFFIX = ".labsdb"


@dataclass(frozen=True)
class WikiRow:
    """One wiki as `meta_p` describes it: who it is, and where to read it."""

    wiki: str
    dbname: str
    section: str
    family: str
    lang: str
    closed: bool


def section_of(value: str) -> str:
    """Return the section name an address wants, from the column's spelling."""
    return _decoded(value).removesuffix(SECTION_SUFFIX).strip()


def _flag(value: object) -> bool:
    """Read one of `meta_p`'s numeric flags, which arrive as decimals."""
    text = _decoded(value)
    return bool(text) and text not in {"0", "0.0", "False", "None"}


#: Positions in a roster row, named because a fixture may be shorter than the
#: query and a wiki with no section is still a wiki.
SECTION_COLUMN: Final = 4
CLOSED_COLUMN: Final = 5


def read_roster(rows: Iterable[Sequence[Any]]) -> tuple[WikiRow, ...]:
    """Turn `meta_p.wiki` rows into addressable wikis, dropping what cannot be one.

    A row with no database name or no host is not a wiki this can read, and a
    row with no section is one whose address cannot be shortened -- that one is
    kept, because `target_for` falls back to the per-wiki alias and reading it
    singly is better than not reading it.
    """
    found: list[WikiRow] = []
    for row in rows:
        dbname, url = _decoded(row[0]), _decoded(row[1])
        host = url.removeprefix("https://").removeprefix("http://").strip("/")
        if not (dbname and host):
            continue
        found.append(
            WikiRow(
                wiki=host,
                dbname=dbname,
                section=section_of(row[4]) if len(row) > SECTION_COLUMN else "",
                family=_decoded(row[2]),
                lang=_decoded(row[3]),
                closed=_flag(row[5]) if len(row) > CLOSED_COLUMN else False,
            )
        )
    return tuple(found)


#: Position of `page_latest` in an enumeration row. Named because a row can be
#: shorter -- a caller reading an older query, or a fixture that predates the
#: column -- and a page with no revision id is still a page.
REVISION_COLUMN: Final = 2


def read_page_titles(rows: Iterable[Sequence[Any]]) -> tuple[tuple[str, str, str], ...]:
    """Give each page its content model, title, and current revision id, in order.

    The order is the answer, not an incidental property of it, so this returns a
    sequence rather than the mapping `read_page_stamps` returns: a dict keyed
    by title would lose the creation ordering the query went to the trouble of
    producing.

    A row with no revision id yields an empty one rather than being dropped. The
    page is real and belongs in the enumeration; what is missing is only the
    shortcut that would have let a sweep skip fetching it.
    """
    found: list[tuple[str, str, str]] = []
    for row in rows:
        model, title = _decoded(row[0]), _decoded(row[1])
        revision = _decoded(row[REVISION_COLUMN]) if len(row) > REVISION_COLUMN and row[REVISION_COLUMN] else ""
        if model and title:
            found.append((model, title, revision))
    return tuple(found)


#: Length of a MediaWiki timestamp, `YYYYMMDDHHMMSS`.
STAMP_LENGTH: Final[int] = 14


def iso_timestamp(stamp: str) -> str:
    """Render a MediaWiki timestamp as an ISO 8601 instant, or "" if it is not one.

    `20040429080822` becomes `2004-04-29T08:08:22Z`. Stored in the wiki's own
    format and converted only on the way out, because that is the form the
    catalogue publishes and `datetime.fromisoformat` is what reads it back --
    `backend.catalog_statistics` parses every date it bins that way.

    Anything that is not fourteen digits yields "" rather than a guess. A blank
    is already the ordinary answer for a page no replica has dated, so every
    consumer of this handles one, and inventing a date from a malformed stamp
    would publish a fact the wiki never stated.
    """
    stamp = stamp.strip()
    if len(stamp) != STAMP_LENGTH or not stamp.isdigit():
        return ""
    return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[8:10]}:{stamp[10:12]}:{stamp[12:14]}Z"


def read_page_stamps(rows: Iterable[Sequence[Any]]) -> dict[str, str]:
    """Map each normalized page title to one MediaWiki timestamp.

    Which timestamp is the query's business, not this function's: the creation
    queries below select the oldest revision and the edit queries the newest,
    and both come back as the same two columns. Named for the shape rather than
    for either meaning so that neither road reads its rows through a function
    that claims to be doing the other one's job.
    """
    found: dict[str, str] = {}
    for row in rows:
        title, stamp = _decoded(row[0]), _decoded(row[1])
        if title and stamp:
            found[title] = stamp
    return found


class PageOrigin(NamedTuple):
    """A page's first surviving revision: when it was made, and who signed it.

    Two fields because the second one is allowed to be missing while the first
    is not. Every page a replica knows has a date; a page whose first author
    MediaWiki suppressed has none, and so does one read before this query
    learned to ask. Callers therefore treat an empty `author` the way they
    already treat an empty date -- publish nothing rather than guess -- instead
    of treating the pair as all-or-nothing.
    """

    stamp: str
    author: str


def read_page_origins(rows: Iterable[Sequence[Any]]) -> dict[str, PageOrigin]:
    """Map each normalized page title to its first revision's date and author.

    The creation queries' three columns, where `read_page_stamps` reads the two
    that every stamp query shares. A row is kept on its date: a page with no
    readable timestamp is a page this cannot say anything about, while a page
    with a date and no author is an ordinary suppressed-author page and is kept
    with an empty name.
    """
    found: dict[str, PageOrigin] = {}
    for row in rows:
        title, stamp, author = _decoded(row[0]), _decoded(row[1]), _decoded(row[2])
        if title and stamp:
            found[title] = PageOrigin(stamp, author)
    return found


# Bounded so a replica that has stopped answering costs a job one slow read
# rather than its whole run. Both are needed: a connect timeout alone still
# leaves a query that has begun free to hang.
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 120


def open_connection(user: Credentials, target: Target) -> Any:  # noqa: ANN401  # pragma: no cover - needs a replica
    """Open one read-only replica connection.

    Excluded from coverage rather than faked: there is nothing here but the
    driver call, every caller takes the connector as an argument, and the tests
    inject their own. `Any` is the driver's own connection type.
    """
    import pymysql  # noqa: PLC0415 - only Toolforge can reach a replica; not a hard dependency of the app

    return pymysql.connect(
        host=target.host,
        user=user.user,
        password=user.password,
        database=target.database,
        charset="utf8mb4",
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=READ_TIMEOUT_SECONDS,
    )


def _rows(
    connect: Connect,
    user: Credentials,
    target: Target,
    sql: str,
    params: Sequence[Any],
) -> tuple[tuple[Any, ...], ...]:
    """Run one parameterized read and return every row, closing the connection."""
    connection = connect(user, target)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return tuple(cursor.fetchall())
    finally:
        connection.close()


class _Borrowed:
    """One pooled connection, lent to a reader that expects to own it.

    Every reader here opens a connection, uses it once and closes it, which is
    the correct shape for a caller reading one wiki. Closing it is the only part
    a pass over many wikis needs to take back, so that is the only part this
    changes: `close` returns the connection to the pool instead of ending it,
    and the pool ends it when the pass does.
    """

    def __init__(self, connection: Any, pool: _Pool, host: str) -> None:  # noqa: ANN401 - the driver's own type
        self._connection = connection
        self._pool = pool
        self._host = host

    def cursor(self) -> Any:  # noqa: ANN401 - the driver's own type
        """Open a cursor on the pooled connection."""
        try:
            return self._connection.cursor()
        except Exception:
            # A connection that cannot produce a cursor is finished, and every
            # later wiki on this section would inherit it. Drop it here so the
            # next one reconnects rather than failing for a reason that has
            # nothing to do with it.
            self._pool.discard(self._host)
            raise

    def close(self) -> None:
        """Release the connection back to the pool, which owns its lifetime."""


class _Pool:
    """The open connections one pass is using, one per replica host.

    The replicas forbid connection pools in the sense that matters -- holding
    connections open while idle, which costs the server memory for nothing and
    which administrators kill on sight. This is the opposite arrangement and is
    worth being precise about: a connection here exists only while a pass is
    actively running queries through it, is reused only by the wikis that share
    its instance, and is closed when the pass ends. Nothing survives a run, and
    nothing sits idle inside one.

    What it buys is the thing the replicas ask for. Reading 1,028 wikis by their
    per-wiki aliases is 1,028 connections; reading them by section is eight.
    """

    def __init__(self, connect: Connect) -> None:
        self._connect = connect
        self._open: dict[str, Any] = {}

    def borrow(self, user: Credentials, target: Target) -> _Borrowed:
        """Return the connection for this target's host, opening one if needed."""
        connection = self._open.get(target.host)
        if connection is None:
            self._open[target.host] = connection = self._connect(user, target)
        else:
            # Same instance, different wiki. `select_db` is what makes one
            # connection serve every database on its section, and it is why the
            # queries themselves need no qualifying and no rewriting.
            connection.select_db(target.database)
        return _Borrowed(connection, self, target.host)

    def discard(self, host: str) -> None:
        """Forget a connection that failed, so the next borrower opens a fresh one."""
        connection = self._open.pop(host, None)
        if connection is not None:
            with suppress(Exception):
                connection.close()

    def close(self) -> None:
        """End every connection this pass opened."""
        for host in list(self._open):
            self.discard(host)


@contextmanager
def pooled(connect: Connect = open_connection) -> Iterator[Connect]:
    """Reuse one connection per replica instance for the length of one pass.

    Yields something every reader in this module already accepts -- a `Connect`
    -- so a caller covering many wikis wraps its pass in this and changes
    nothing else. Readers still open, use and close a connection each; those
    calls are simply answered from the pool while the pass lasts.

    Only pays off when the targets share a host, which is what passing a section
    to `target_for` arranges. Without one, every wiki addresses its own alias,
    every borrow is a miss, and this costs one dictionary lookup per read.
    """
    pool = _Pool(connect)
    try:
        yield pool.borrow
    finally:
        pool.close()


def dbnames_for(
    wikis: Sequence[str],
    *,
    user: Credentials,
    connect: Connect = open_connection,
) -> dict[str, str]:
    """Ask `meta_p` which database serves each named wiki host.

    Asked rather than derived. The host-to-database rule has enough exceptions
    (`www.wikidata.org` is `wikidatawiki`, `meta.wikimedia.org` is `metawiki`)
    that a local copy of the rule would be a second source of truth, and this
    is one query for every wiki the caller cares about.
    """
    if not wikis:
        return {}
    placeholders = ", ".join(["%s"] * len(wikis))
    rows = _rows(
        connect,
        user,
        target_for(META_DB),
        DBNAME_QUERY.format(placeholders=placeholders),
        [url_for(wiki) for wiki in wikis],
    )
    return read_dbnames(rows)


@dataclass(frozen=True)
class Address:
    """Where one wiki is read: which database, and which instance it is on.

    The section is optional because it only ever makes the address shorter. A
    caller that has one gets a shared connection; a caller that does not gets
    the per-wiki alias, which has always worked and still does.
    """

    dbname: str
    section: str = ""


def resolve(
    wikis: Sequence[str],
    *,
    connect: Connect = open_connection,
    known: Mapping[str, Address] | None = None,
) -> tuple[Credentials | None, dict[str, Address]]:
    """Work out how to reach each wiki, asking `meta_p` only about the ones left.

    `known` is what the caller already has -- the registry stores a database and
    a section for every wiki it has ever seen, so a scheduled pass supplies the
    lot and this never opens a `meta_p` connection at all. Anything not in it,
    such as a wiki named by hand in an operator override, is looked up.

    Best effort, which is the contract every caller of this was already written
    to: no `replica.my.cnf` yields no credentials and no addresses, and a
    `meta_p` that will not answer yields whatever the caller already knew. Both
    read downstream as "there was nothing to do here", which is the truth.
    """
    user = credentials()
    if user is None:
        return None, {}
    wanted = list(dict.fromkeys(wikis))
    found = {wiki: address for wiki, address in (known or {}).items() if wiki in set(wanted) and address.dbname}
    missing = [wiki for wiki in wanted if wiki not in found]
    if not missing:
        return user, found
    try:
        dbnames = dbnames_for(missing, user=user, connect=connect)
    except Exception:  # noqa: BLE001 - an unreachable meta_p is not a failed census
        return user, found
    for wiki, dbname in dbnames.items():
        found[wiki] = Address(dbname=dbname)
    return user, found


def roster_for(
    *,
    user: Credentials,
    connect: Connect = open_connection,
) -> tuple[WikiRow, ...]:
    """Ask `meta_p` for every wiki that can be read, and where each one lives.

    One connection and one unfiltered read of a table of about a thousand rows,
    which is why the roster is fetched whole rather than asked per wiki. The
    alternative -- `dbnames_for` on the wikis a pass is about to cover -- costs
    a `meta_p` connection on every run of every lane to re-learn something that
    changes when a wiki is created or closed.
    """
    return read_roster(_rows(connect, user, target_for(META_DB), ROSTER_QUERY, []))


def creation_origins_for(
    dbname: str,
    *,
    section: str = "",
    user: Credentials,
    connect: Connect = open_connection,
) -> dict[str, PageOrigin]:
    """Return every user-space script page's first revision, by normalized title."""
    rows = _rows(
        connect,
        user,
        target_for(dbname, section),
        CREATION_QUERY,
        [USER_NAMESPACE, *TITLE_PATTERNS],
    )
    return read_page_origins(rows)


def gadget_creation_origins_for(
    dbname: str,
    *,
    section: str = "",
    user: Credentials,
    connect: Connect = open_connection,
) -> dict[str, PageOrigin]:
    """Return every gadget code page's first revision, keyed as it is stored.

    Keys keep the `Gadget-` prefix and the replica's underscores, because that
    is the form a declaration's file name is turned into to look one up. Only
    page metadata is read -- a title, the oldest revision timestamp, and the
    name signed to it -- for the reason `backend.userscript_creation_dates`
    gives at length.
    """
    rows = _rows(
        connect,
        user,
        target_for(dbname, section),
        GADGET_CREATION_QUERY,
        [MEDIAWIKI_NAMESPACE, f"{GADGET_TITLE_PREFIX}%"],
    )
    return read_page_origins(rows)


def script_edit_dates_for(
    dbname: str,
    *,
    section: str = "",
    user: Credentials,
    connect: Connect = open_connection,
) -> dict[str, str]:
    """Return every user-space script page's last edit timestamp, by normalized title.

    Asked of the replica even though the census already learns the same fact
    from the API, because the two answer for different sets. The API tells us
    when a page was last edited only as a side effect of fetching its body, and
    a sweep deliberately does not fetch a page whose `page_latest` has not
    moved. That is what makes a second sweep cheap, and it means a page stored
    before this column existed would keep its blank until somebody happened to
    edit it. One indexed query per wiki dates the whole corpus instead.
    """
    rows = _rows(
        connect,
        user,
        target_for(dbname, section),
        SCRIPT_EDIT_QUERY,
        [USER_NAMESPACE, *TITLE_PATTERNS],
    )
    return read_page_stamps(rows)


def gadget_edit_dates_for(
    dbname: str,
    *,
    section: str = "",
    user: Credentials,
    connect: Connect = open_connection,
) -> dict[str, str]:
    """Return every gadget code page's last edit timestamp, keyed as it is stored.

    The gadget census has no API road to this at all: it reads one definition
    page per wiki and never fetches the code, so without this query a gadget
    rewritten every week and one untouched since 2009 are indistinguishable to
    the catalogue.
    """
    rows = _rows(
        connect,
        user,
        target_for(dbname, section),
        GADGET_EDIT_QUERY,
        [MEDIAWIKI_NAMESPACE, f"{GADGET_TITLE_PREFIX}%"],
    )
    return read_page_stamps(rows)


def script_titles_for(
    dbname: str,
    *,
    section: str = "",
    user: Credentials,
    connect: Connect = open_connection,
) -> tuple[tuple[str, str, str], ...]:
    """Every user-space script page on one wiki, in creation order, with its model.

    Titles come back in the replica's own spelling -- no namespace, underscores
    for spaces -- because that is what the column holds. Putting a title back
    into the form the API answers with needs the wiki's own name for namespace
    2, which is not in this database, so it is done by the caller that has an
    API to ask.
    """
    rows = _rows(
        connect,
        user,
        target_for(dbname, section),
        ENUMERATION_QUERY,
        [USER_NAMESPACE, *SCRIPT_MODELS],
    )
    return read_page_titles(rows)
