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

Only page metadata is read. The `revision` table carries actor ids and comments;
this asks for a page id and a timestamp, and the directory stores counts of
people rather than people, so there is nothing here to leak.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

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


def target_for(dbname: str) -> Target:
    """Return where to reach one wiki's replica, by its database name."""
    return Target(host=f"{dbname}{HOST_SUFFIX}", database=f"{dbname}_p")


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

# MIN(rev_timestamp) is the earliest surviving revision. Revisions removed by
# deletion live in `archive` and are deliberately not consulted: a page whose
# first edits were deleted reads as very slightly newer than it was, which is
# immaterial to an ordering, and reading `archive` would mean reading rows an
# administrator chose to withdraw.
CREATION_QUERY = (
    "SELECT p.page_title, MIN(r.rev_timestamp) "
    "FROM page p JOIN revision r ON r.rev_page = p.page_id "
    "WHERE p.page_namespace = %s AND (p.page_title LIKE %s OR p.page_title LIKE %s) "
    "GROUP BY p.page_id"
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
    "SELECT p.page_title, MIN(r.rev_timestamp) "
    "FROM page p JOIN revision r ON r.rev_page = p.page_id "
    "WHERE p.page_namespace = %s AND p.page_title LIKE %s "
    "GROUP BY p.page_id"
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


#: Position of `page_latest` in an enumeration row. Named because a row can be
#: shorter -- a caller reading an older query, or a fixture that predates the
#: column -- and a page with no revision id is still a page.
REVISION_COLUMN: Final = 2


def read_page_titles(rows: Iterable[Sequence[Any]]) -> tuple[tuple[str, str, str], ...]:
    """Give each page its content model, title, and current revision id, in order.

    The order is the answer, not an incidental property of it, so this returns a
    sequence rather than the mapping `read_creation_dates` returns: a dict keyed
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


def read_creation_dates(rows: Iterable[Sequence[Any]]) -> dict[str, str]:
    """Map each normalized page title to its MediaWiki creation timestamp."""
    found: dict[str, str] = {}
    for row in rows:
        title, stamp = _decoded(row[0]), _decoded(row[1])
        if title and stamp:
            found[title] = stamp
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


def creation_dates_for(
    dbname: str,
    *,
    user: Credentials,
    connect: Connect = open_connection,
) -> dict[str, str]:
    """Return every user-space script page's creation timestamp, by normalized title."""
    rows = _rows(
        connect,
        user,
        target_for(dbname),
        CREATION_QUERY,
        [USER_NAMESPACE, *TITLE_PATTERNS],
    )
    return read_creation_dates(rows)


def gadget_creation_dates_for(
    dbname: str,
    *,
    user: Credentials,
    connect: Connect = open_connection,
) -> dict[str, str]:
    """Return every gadget code page's creation timestamp, keyed as it is stored.

    Keys keep the `Gadget-` prefix and the replica's underscores, because that
    is the form a declaration's file name is turned into to look one up. Only
    page metadata is read -- a title and the oldest revision timestamp -- for
    the reason `backend.userscript_creation_dates` gives at length.
    """
    rows = _rows(
        connect,
        user,
        target_for(dbname),
        GADGET_CREATION_QUERY,
        [MEDIAWIKI_NAMESPACE, f"{GADGET_TITLE_PREFIX}%"],
    )
    return read_creation_dates(rows)


def script_titles_for(
    dbname: str,
    *,
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
        target_for(dbname),
        ENUMERATION_QUERY,
        [USER_NAMESPACE, *SCRIPT_MODELS],
    )
    return read_page_titles(rows)
