# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialect-specific ranked-search index DDL for the canonical tool cache.

SQLAlchemy's create_all cannot express an FTS5 virtual table or add a
FULLTEXT index to an existing table, so this module owns that DDL. All
statements are idempotent (IF NOT EXISTS) because init_schema runs in every
worker process at startup. Population of a freshly created FTS table is
row-proportional and therefore lives in proxy/migrate.py, not here.
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

_log = logging.getLogger(__name__)

# Standalone FTS5 table rather than external-content: canonical_tool_cache has
# a TEXT primary key and external content requires an INTEGER rowid. At most
# ~5k rows x 4KB search_text, so duplicating the haystack is cheap.
_SQLITE_STATEMENTS = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS canonical_tool_search
    USING fts5(tool_name UNINDEXED, search_text)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS canonical_tool_search_ai
    AFTER INSERT ON canonical_tool_cache BEGIN
      INSERT INTO canonical_tool_search(tool_name, search_text)
      VALUES (new.tool_name, new.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS canonical_tool_search_au
    AFTER UPDATE OF search_text, tool_name ON canonical_tool_cache BEGIN
      DELETE FROM canonical_tool_search WHERE tool_name = old.tool_name;
      INSERT INTO canonical_tool_search(tool_name, search_text)
      VALUES (new.tool_name, new.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS canonical_tool_search_ad
    AFTER DELETE ON canonical_tool_cache BEGIN
      DELETE FROM canonical_tool_search WHERE tool_name = old.tool_name;
    END
    """,
)


def mariadb_statements() -> tuple[str, ...]:
    """Return the MariaDB DDL as data so tests can pin it without a MariaDB."""
    return (
        """
        ALTER TABLE canonical_tool_cache
        ADD FULLTEXT INDEX IF NOT EXISTS ft_canonical_search_text (search_text)
        """,
    )


def ensure_search_index(engine: Engine) -> bool:
    """Create the SQLite ranked-search index if missing.

    SQLite only, deliberately: creating a table's FIRST InnoDB FULLTEXT
    index rebuilds the table — row-proportional work that must not run in
    init_schema (every uWSGI worker executes it at startup; see
    proxy/migrate.py's docstring for why that pattern causes outages). The
    MariaDB index is created once per deploy by the migrate.py migration
    below. Returns False rather than raising when DDL fails: search degrades
    to the LIKE fallback, which must never take the app down — but the
    failure is logged loudly, because a silent False means production
    quietly running unranked forever.
    """
    if engine.dialect.name != "sqlite":
        return False
    try:
        with engine.begin() as conn:
            for statement in _SQLITE_STATEMENTS:
                conn.execute(text(statement))
    except SQLAlchemyError:
        _log.exception("ranked-search index DDL failed; search degrades to LIKE")
        return False
    return True
