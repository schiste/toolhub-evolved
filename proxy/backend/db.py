# SPDX-License-Identifier: GPL-3.0-or-later
"""Database engine + session plumbing (SQLAlchemy).

SQLite (repo-local file) in development and tests; ToolsDB (MariaDB via
PyMySQL) on Toolforge through the TOOLHUB_DB_URL env var. `configure()` may be
called again with a new URL (tests do this per-fixture) — the previous engine
is disposed.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _schema_additions() -> dict[str, dict[str, str]]:
    """Columns added after the first Toolforge deployment.

    `Base.metadata.create_all()` creates missing tables but intentionally does
    not mutate existing tables. These additive DDL snippets are the small,
    explicit migration layer the runbook calls for until schema churn justifies
    Alembic.
    """
    text_col = "LONGTEXT" if engine().dialect.name in {"mysql", "mariadb"} else "TEXT"
    json_col = "JSON"
    true_default = "TRUE" if engine().dialect.name in {"mysql", "mariadb"} else "1"
    return {
        "users": {
            "role": "VARCHAR(32) NOT NULL DEFAULT 'user'",
            "session_epoch": "INTEGER NOT NULL DEFAULT 0",
        },
        "toolhub_tokens": {
            "last_validated_at": "DATETIME NULL",
            "last_failure_at": "DATETIME NULL",
        },
        "favorites": {
            "created_by_user_id": "INTEGER NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'local_draft'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
        },
        "lists": {
            "created_by_user_id": "INTEGER NULL",
            "official_list_id": "INTEGER NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'local_draft'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
            "last_toolhub_response": f"{json_col} NULL",
            "validation_errors": f"{json_col} NULL",
            "deleted_at": "DATETIME NULL",
        },
        "tools": {
            "created_by_user_id": "INTEGER NULL",
            "official_name": "VARCHAR(255) NULL",
            "visibility": "VARCHAR(32) NOT NULL DEFAULT 'private'",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'local_draft'",
            "review_status": "VARCHAR(32) NOT NULL DEFAULT 'approved'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
            "last_toolhub_response": f"{json_col} NULL",
            "validation_errors": f"{json_col} NULL",
            "deleted_at": "DATETIME NULL",
        },
        "tool_overlays": {
            "created_by_user_id": "INTEGER NULL",
            "base_revision": "VARCHAR(255) NULL",
            "field_statuses": f"{json_col} NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'local_draft'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
            "last_toolhub_response": f"{json_col} NULL",
            "validation_errors": f"{json_col} NULL",
            "review_status": "VARCHAR(32) NOT NULL DEFAULT 'open'",
            "deleted_at": "DATETIME NULL",
        },
        "activity": {
            "created_by_user_id": "INTEGER NULL",
            "object_type": "VARCHAR(32) NULL",
            "object_key": "VARCHAR(255) NULL",
            "action": "VARCHAR(64) NULL",
            "official_status": "VARCHAR(32) NULL",
            "payload": f"{json_col} NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
        },
        "crawler_urls": {
            "created_by_user_id": "INTEGER NULL",
            "official_crawler_url_id": "INTEGER NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "enabled": f"BOOLEAN NOT NULL DEFAULT {true_default}",
            "last_checked_at": "DATETIME NULL",
            "last_status": "VARCHAR(64) NULL",
            "last_error": f"{text_col} NULL",
            "last_toolhub_response": f"{json_col} NULL",
            "validation_errors": f"{json_col} NULL",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'local_draft'",
            "last_synced_at": "DATETIME NULL",
        },
        "crawler_runs": {
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
        },
        "tool_events": {
            "created_by_user_id": "INTEGER NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
        },
        "tool_thanks": {
            "created_by_user_id": "INTEGER NULL",
            "review_status": "VARCHAR(32) NOT NULL DEFAULT 'approved'",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
        },
        "source_analysis_reports": {
            "created_by_user_id": "INTEGER NULL",
            "review_notes": f"{text_col} NULL",
            "reviewed_at": "DATETIME NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
        },
        "tool_catalog_sync_state": {
            "reconcile_next_page": "INTEGER NOT NULL DEFAULT 1",
            "reconcile_cycles_completed": "INTEGER NOT NULL DEFAULT 0",
            "reconcile_last_at": "DATETIME NULL",
            "recent_latest_marker": "VARCHAR(255) NULL",
            "recent_pending_tools": f"{json_col} NULL",
            "recent_last_at": "DATETIME NULL",
            "detail_hydration_cursor": "VARCHAR(255) NULL",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'idle'",
            "last_started_at": "DATETIME NULL",
            "last_success_at": "DATETIME NULL",
            "last_completed_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'official'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'official'",
        },
        "repository_analysis_state": {
            "attempts": "INTEGER NOT NULL DEFAULT 0",
        },
        "person_reconciliation_queue": {
            "attempts": "INTEGER NOT NULL DEFAULT 0",
        },
        "tool_maintainer_edges": {
            "wiki_username": "VARCHAR(255) NOT NULL DEFAULT ''",
        },
        "tool_health_targets": {
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
            "review_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
            "last_synced_at": "DATETIME NULL",
            "deleted_at": "DATETIME NULL",
        },
        "tool_health_checks": {
            "source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
        },
        "tool_media": {
            "created_by_user_id": "INTEGER NULL",
            "review_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'evolved_real'",
            "last_synced_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
            "deleted_at": "DATETIME NULL",
        },
    }


def _upgrade_schema() -> None:
    """Apply idempotent additive migrations for existing deployments."""
    eng = engine()
    inspector = inspect(eng)
    existing_tables = set(inspector.get_table_names())
    with eng.begin() as conn:
        for table, columns in _schema_additions().items():
            if table not in existing_tables:
                continue
            existing_columns = {col["name"] for col in inspect(conn).get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing_columns:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        for table in ("repository_analysis_state", "person_reconciliation_queue"):
            if table in existing_tables:
                conn.exec_driver_sql(f"UPDATE {table} SET attempts = 0 WHERE attempts IS NULL")


def configure(url: str) -> None:
    """Create (or replace) the process-wide engine and session factory."""
    global _engine, _session_factory  # noqa: PLW0603 — module-level singleton by design
    if _engine is not None:
        _engine.dispose()
    if url in {"sqlite://", "sqlite:///:memory:"}:
        # In-memory SQLite: share the one database across connections/threads.
        _engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        _engine = create_engine(url, pool_pre_ping=True)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)


def engine() -> Engine:
    """Return the configured engine (configure() must have run)."""
    if _engine is None:
        msg = "backend.db.configure() has not been called"
        raise RuntimeError(msg)
    return _engine


def init_schema() -> None:
    """Create any missing tables (idempotent; see docs/RUNBOOK.md for changes)."""
    Base.metadata.create_all(engine())
    _upgrade_schema()


@contextmanager
def advisory_lock(name: str, *, timeout_seconds: int = 0) -> Iterator[bool]:
    """Hold a best-effort process lock on MariaDB; remain a no-op on SQLite."""
    if engine().dialect.name not in {"mysql", "mariadb"}:
        yield True
        return
    connection = engine().connect()
    acquired = False
    try:
        acquired = connection.scalar(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": name, "timeout": max(0, int(timeout_seconds))},
        ) == 1
        yield acquired
    finally:
        if acquired:
            connection.scalar(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
        connection.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on error."""
    if _session_factory is None:
        msg = "backend.db.configure() has not been called"
        raise RuntimeError(msg)
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
