# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the one-off data migration entrypoint (proxy/migrate.py).

These cover the two properties that make it safe to run from a deploy: it is
idempotent, and it refuses to silently migrate the wrong database.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import migrate  # noqa: E402
from backend import api_cache, canonical_tools, db, maintainer_index  # noqa: E402
from backend.models import ApiCache, ToolAuthorClaim, ToolAuthorKey, User, UserToolResolverCache, utcnow  # noqa: E402
from backend import sync  # noqa: E402


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


def test_migrate_cleans_legacy_resolver_identity_claims_and_caches(configured_db):
    now = utcnow()
    with db.session_scope() as s:
        user = User(wm_sub="schiste", username="Schiste")
        s.add(user)
        s.flush()
        s.add_all(
            [
                ToolAuthorClaim(
                    tool_name="wrong-tool",
                    author_name="Effeietsanders",
                    toolhub_username="Schiste",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                ),
                ToolAuthorClaim(
                    tool_name="wrong-tool-2",
                    author_name="Effeietsanders",
                    toolhub_username="Schiste",
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                ),
                ToolAuthorClaim(
                    tool_name="signed-tool",
                    author_name="Maintainer Alias",
                    toolhub_username="Schiste",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
                ),
                ToolAuthorKey(toolhub_username="Schiste", key_id="legacy-key", public_key="pk"),
                UserToolResolverCache(
                    user_id=user.id,
                    payload={"possible": [{"tool": {"name": "wrong-tool"}}]},
                    computed_at=now,
                    expires_at=now + timedelta(minutes=5),
                    stale_until=now + timedelta(days=1),
                ),
            ]
        )

    first = {result.name: result.rows for result in migrate.run_once()}
    assert first["resolver identity cleanup"] == 3
    with db.session_scope() as s:
        assert (
            s.query(ToolAuthorClaim).filter(ToolAuthorClaim.tool_name.in_(["wrong-tool", "wrong-tool-2"])).count() == 0
        )
        signed_claim = s.query(ToolAuthorClaim).filter(ToolAuthorClaim.tool_name == "signed-tool").one()
        migrated_user = s.query(User).one()
        assert signed_claim.user_id == migrated_user.id
        assert s.query(ToolAuthorKey).one().user_id == migrated_user.id
        assert s.query(UserToolResolverCache).count() == 0

    second = {result.name: result.rows for result in migrate.run_once()}
    assert second["resolver identity cleanup"] == 0


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
