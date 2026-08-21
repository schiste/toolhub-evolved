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
from typing import TYPE_CHECKING, Any

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
#: Suffixes the census recognizes. Content model decides what is a script, but
#: the replica has no content model, so the query narrows by title and lets the
#: census's own classification do the rest.
TITLE_PATTERNS = ("%.js", "%.css")


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
