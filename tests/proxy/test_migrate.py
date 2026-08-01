# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the one-off data migration entrypoint (proxy/migrate.py).

These cover the two properties that make it safe to run from a deploy: it is
idempotent, and it refuses to silently migrate the wrong database.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import migrate  # noqa: E402
from backend import api_cache, canonical_tools, db  # noqa: E402
from backend.models import ApiCache  # noqa: E402


@pytest.fixture
def configured_db(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'migrate.sqlite3'}")
    db.init_schema()
    return None


def test_migrate_backfills_both_caches_and_is_idempotent(configured_db, capsys):
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/legacy/",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    canonical_tools.upsert_records(
        [{"name": "legacy-tool", "title": "Legacy", "description": "cached earlier"}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )
    # Simulate rows written before either column existed.
    with db.session_scope() as s:
        s.query(ApiCache).update({ApiCache.path: "", ApiCache.collection: "", ApiCache.detail_key: ""})
        s.execute(db.text("UPDATE canonical_tool_cache SET search_text = ''"))

    # Asserted per migration rather than as a whole set, so adding a migration
    # extends this rather than breaking it.
    first = {result.name: result.rows for result in migrate.run_once()}
    assert first["api_cache index columns"] == 1
    assert first["canonical search_text"] == 1

    # Running again is a no-op, so a deploy can re-run it without thinking.
    second = {result.name: result.rows for result in migrate.run_once()}
    assert second["api_cache index columns"] == 0
    assert second["canonical search_text"] == 0
    assert [r for r in canonical_tools.search("cached earlier")][0]["toolName"] == "legacy-tool"


def test_schema_setup_does_no_row_level_work(configured_db):
    """init_schema() runs in every worker at startup, so it must stay DDL-only.

    A backfill here executes once per process on every restart, with several
    workers doing it at once against a table live requests need. That is what
    took the site down; the work belongs in migrate.py, which runs once before
    the restart.
    """
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/legacy/",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    canonical_tools.upsert_records(
        [{"name": "legacy-tool", "title": "Legacy", "description": "cached earlier"}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )
    with db.session_scope() as s:
        s.query(ApiCache).update({ApiCache.path: "", ApiCache.collection: "", ApiCache.detail_key: ""})
        s.execute(db.text("UPDATE canonical_tool_cache SET search_text = ''"))

    db.init_schema()

    # Untouched by schema setup — and still present, never dropped.
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 1
        assert s.query(ApiCache).one().path == ""
        assert s.execute(db.text("SELECT search_text FROM canonical_tool_cache")).scalar() == ""
    # Only the explicit migration does the row work.
    migrated = {result.name: result.rows for result in migrate.run_once()}
    assert migrated["api_cache index columns"] == 1
    assert migrated["canonical search_text"] == 1


def test_migrate_refuses_to_run_against_the_unconfigured_default(monkeypatch, capsys):
    """The guard for the mistake that matters: migrating a stale local database.

    Toolforge injects the tool environment into webservice and job pods only, so
    a deploy step run from a plain `become` shell sees no TOOLHUB_DB_URL, falls
    back to the repo-local SQLite file, and reports success having touched
    nothing real.
    """
    monkeypatch.delenv("TOOLHUB_DB_URL", raising=False)
    assert migrate.main(["--require-configured-db"]) == 1
    assert "TOOLHUB_DB_URL is unset" in capsys.readouterr().err


def test_migrate_runs_against_a_configured_database(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path / 'configured.sqlite3'}")
    assert migrate.main(["--require-configured-db"]) == 0
    out = capsys.readouterr().out
    assert "configured_db_url=yes" in out
    assert "api_cache index columns" in out
