# SPDX-License-Identifier: GPL-3.0-or-later
"""Ranked canonical-catalog search across both database backends."""

from datetime import timedelta

import pytest
from sqlalchemy import text, update

from backend import canonical_tools, db
from backend.models import CanonicalToolCache, utcnow


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def _add_tool(s, name, *, title="", description="", keywords=None, fetched_at=None):
    s.add(
        CanonicalToolCache(
            tool_name=name,
            record={
                "name": name,
                "title": title,
                "description": description,
                "keywords": keywords or [],
            },
            fetched_at=fetched_at or utcnow(),
            expires_at=utcnow() + timedelta(hours=1),
            stale_until=utcnow() + timedelta(hours=2),
        )
    )


# Task 1: Fold keywords into search_text
def test_search_text_includes_keywords():
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="Edit stream", keywords=["citation", "bot"])
    with db.session_scope() as s:
        row = s.query(CanonicalToolCache).one()
        assert "citation" in row.search_text
        assert "bot" in row.search_text


def test_search_text_ignores_malformed_keywords():
    with db.session_scope() as s:
        _add_tool(s, "weird", title="w", description="d")
        s.add(
            CanonicalToolCache(
                tool_name="weird2",
                record={"name": "weird2", "keywords": "not-a-list"},
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )
    with db.session_scope() as s:
        assert s.query(CanonicalToolCache).count() == 2


def test_search_text_re_derives_on_record_update():
    """Verify keywords are re-derived whenever record is updated."""
    with db.session_scope() as s:
        _add_tool(s, "test", title="Test", description="Test tool", keywords=["old"])
    with db.session_scope() as s:
        row = s.query(CanonicalToolCache).one()
        old_text = row.search_text
        assert "old" in row.search_text
        # Simulate an update via record reassignment (which triggers _derive_search_text)
        row.record = {
            "name": "test",
            "title": "Test",
            "description": "Test tool",
            "keywords": ["new"],
        }
    with db.session_scope() as s:
        row = s.query(CanonicalToolCache).one()
        assert "new" in row.search_text
        assert row.search_text != old_text


# Task 2: Search-index DDL
def test_fts_table_and_triggers_created_on_sqlite():
    from backend import search_index
    with db.session_scope() as s:
        names = {
            row[0]
            for row in s.execute(
                text("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")
            )
        }
    assert "canonical_tool_search" in names
    assert {"canonical_tool_search_ai", "canonical_tool_search_au", "canonical_tool_search_ad"} <= names


def test_fts_rows_follow_cache_rows():
    from backend import search_index
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="stream", keywords=["bot"])
    with db.session_scope() as s:
        assert s.execute(
            text("SELECT count(*) FROM canonical_tool_search WHERE tool_name = 'sfedits'")
        ).scalar() == 1
        s.execute(text("DELETE FROM canonical_tool_cache WHERE tool_name = 'sfedits'"))
    with db.session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM canonical_tool_search")).scalar() == 0


def test_mariadb_ddl_statements_are_stable():
    from backend import search_index
    statements = search_index.mariadb_statements()
    assert any("ADD FULLTEXT INDEX IF NOT EXISTS" in stmt for stmt in statements)
    assert any("canonical_tool_cache" in stmt for stmt in statements)


def test_migration_rederives_search_text_keywords():
    """Test the rederive migration that backfills keywords into search_text."""
    with db.session_scope() as s:
        # Create a row, then manually clear its search_text to simulate pre-keyword state
        row = CanonicalToolCache(
            tool_name="oldstyle",
            record={
                "name": "oldstyle",
                "title": "Old Tool",
                "description": "Pre-keyword",
                "keywords": ["newkw"]
            },
            source_url="https://example.org",
            fetched_at=utcnow(),
            expires_at=utcnow(),
            stale_until=utcnow(),
        )
        s.add(row)
        s.flush()
        # Simulate old search_text without keywords by directly updating the column
        s.execute(
            update(CanonicalToolCache)
            .where(CanonicalToolCache.tool_name == "oldstyle")
            .values(search_text="oldstyle\nold tool\npre-keyword")
        )

    # Run the migration
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "proxy"))
    import migrate
    touched = migrate.rederive_search_text_keywords()
    assert touched == 1

    # Verify keywords are now in search_text
    with db.session_scope() as s:
        row = s.query(CanonicalToolCache).filter_by(tool_name="oldstyle").one()
        assert "newkw" in row.search_text

    # Run again - should touch 0
    touched = migrate.rederive_search_text_keywords()
    assert touched == 0


# Task 3: Ranked search
def test_search_keeps_substring_recall():
    """The SPA search box sends partial words; ranked search must not lose them."""
    with db.session_scope() as s:
        _add_tool(
            s,
            "citation-hunt",
            title="Citation Hunt",
            description="Find unsourced statements",
            keywords=["citation"],
        )
        _add_tool(s, "sfedits", title="SF edits", description="stream")
    assert "citation-hunt" in [r["toolName"] for r in canonical_tools.search("citat")]
    assert "sfedits" in [r["toolName"] for r in canonical_tools.search("sf")]  # < min token size


def test_search_ranks_by_relevance_not_recency():
    with db.session_scope() as s:
        # Older row is the better match; recency ordering would invert this.
        _add_tool(
            s,
            "citation-hunt",
            title="Citation Hunt",
            description="Find unsourced statements and add citations",
            keywords=["citation", "references"],
            fetched_at=utcnow() - timedelta(days=30),
        )
        _add_tool(
            s,
            "freshtool",
            title="Fresh tool",
            description="Mentions citation once",
            fetched_at=utcnow(),
        )
    results = canonical_tools.search("citation")
    assert [r["toolName"] for r in results][0] == "citation-hunt"
    # Response contract unchanged: same payload keys as tools_by_name.
    assert {"toolName", "record", "sourceUrl", "source", "syncStatus"} <= set(results[0])


def test_search_survives_fts_syntax_characters():
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="stream")
    for hostile in ('citation" OR', "a-b", "col:umn", '""', "*"):
        assert isinstance(canonical_tools.search(hostile), list)


def test_search_empty_query_and_fallback():
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="stream")
    assert canonical_tools.search("")  # empty query: recency-ordered listing
    with db.session_scope() as s:
        s.execute(text("DROP TABLE canonical_tool_search"))
    assert [r["toolName"] for r in canonical_tools.search("edits")] == ["sfedits"]  # LIKE fallback


def test_canonical_tools_search_contract():
    """Verify search() returns required payload keys in the response."""
    with db.session_scope() as s:
        _add_tool(
            s,
            "citation-hunt",
            title="Citation Hunt",
            description="Find unsourced statements",
            keywords=["citation"],
        )
        _add_tool(s, "sfedits", title="SF edits", description="stream")

    results = canonical_tools.search("citation")
    assert isinstance(results, list)
    assert len(results) > 0
    result = results[0]
    # Response contract unchanged: same payload keys as tools_by_name
    assert {"toolName", "record", "sourceUrl", "source", "syncStatus"} <= set(result)
