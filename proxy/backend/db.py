# SPDX-License-Identifier: GPL-3.0-or-later
"""Database engine + session plumbing (SQLAlchemy).

SQLite (repo-local file) in development and tests; ToolsDB (MariaDB via
PyMySQL) on Toolforge through the TOOLHUB_DB_URL env var. `configure()` may be
called again with a new URL (tests do this per-fixture) — the previous engine
is disposed.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base

T = TypeVar("T")

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None

# Per-worker connection budget. Four webservice workers x (2 + 2) = 16, inside
# ToolsDB's 20-per-account limit with headroom for the scheduled jobs. Most
# requests are static files or shared-cache hits and never take a connection at
# all, so a small pool is not the bottleneck; exceeding the account limit would
# be, and it fails as connection errors rather than as slowness.
POOL_SIZE_PER_WORKER = 2
POOL_OVERFLOW_PER_WORKER = 2
# ToolsDB drops idle connections; recycle below that so a pooled connection is
# never handed out already dead.
POOL_RECYCLE_SECONDS = 280
# Wait briefly for a free connection, then fail loudly rather than pile up.
POOL_TIMEOUT_SECONDS = 10


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
        "api_cache": {
            "path": "VARCHAR(512) NOT NULL DEFAULT ''",
            "collection": "VARCHAR(64) NOT NULL DEFAULT ''",
            "detail_key": "VARCHAR(255) NOT NULL DEFAULT ''",
        },
        "users": {
            "role": "VARCHAR(32) NOT NULL DEFAULT 'user'",
            "session_epoch": "INTEGER NOT NULL DEFAULT 0",
            "person_id": "INTEGER NULL",
            "wikimedia_global_user_id": "VARCHAR(64) NULL",
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
            "skipped": f"{json_col} NULL",
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
            "snapshot_generation": "INTEGER NOT NULL DEFAULT 0",
            "snapshot_next_page": "INTEGER NOT NULL DEFAULT 1",
            "snapshot_expected_count": "INTEGER NOT NULL DEFAULT 0",
            "snapshot_started_at": "DATETIME NULL",
            "recent_latest_marker": "VARCHAR(255) NULL",
            "recent_pending_tools": f"{json_col} NULL",
            "recent_scan_page": "INTEGER NOT NULL DEFAULT 1",
            "recent_scan_latest_marker": "VARCHAR(255) NULL",
            "recent_scan_boundary_marker": "VARCHAR(255) NULL",
            "recent_cursor_recovery_required": "BOOLEAN NOT NULL DEFAULT 0",
            "recent_last_at": "DATETIME NULL",
            "detail_hydration_cursor": "VARCHAR(255) NULL",
            "detail_hydration_pending_tools": f"{json_col} NULL",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'idle'",
            "last_started_at": "DATETIME NULL",
            "last_success_at": "DATETIME NULL",
            "last_completed_at": "DATETIME NULL",
            "last_error": f"{text_col} NULL",
            "source": "VARCHAR(32) NOT NULL DEFAULT 'official'",
            "sync_status": "VARCHAR(32) NOT NULL DEFAULT 'official'",
        },
        "canonical_tool_cache": {
            "search_text": f"{text_col} NULL",
            "card_record": f"{json_col} NULL",
            "modified_at_sort": "DATETIME NULL",
            "generation": "INTEGER NOT NULL DEFAULT 0",
            # Empty is the correct value for every row that existed before this
            # column did: nothing had measured whether anybody used them, and
            # saying so is what the empty value means.
            "lifecycle": "VARCHAR(16) NOT NULL DEFAULT ''",
            # NULL, not 0: an un-backfilled row must be distinguishable from a
            # tool that is genuinely not deprecated, or the Status counts go
            # quietly wrong instead of visibly unfinished.
            "deprecated": "BOOLEAN NULL",
            "experimental": "BOOLEAN NULL",
        },
        "toolforge_account_projection": {
            "developer_username": "VARCHAR(255) NOT NULL DEFAULT ''",
            "normalized_developer_username": "VARCHAR(255) NOT NULL DEFAULT ''",
            "ldap_created_at": "VARCHAR(32) NOT NULL DEFAULT ''",
        },
        "people": {
            # Filled by the one-off data migration. UUID generation is kept out
            # of worker-start DDL because it is proportional to row count.
            "public_id": "VARCHAR(36) NULL",
            "public_slug": "VARCHAR(96) NULL",
        },
        "person_tool_relationships": {
            "verified_at": "DATETIME NULL",
        },
        "person_identifiers": {
            "identifier_kind": "VARCHAR(32) NOT NULL DEFAULT 'handle'",
            "source": "VARCHAR(64) NOT NULL DEFAULT 'local'",
            "is_current": f"BOOLEAN NOT NULL DEFAULT {true_default}",
            "verified_at": "DATETIME NULL",
            "last_seen_at": "DATETIME NULL",
            "retired_at": "DATETIME NULL",
            "updated_at": "DATETIME NULL",
        },
        "tool_author_claims": {
            "user_id": "INTEGER NULL",
            "requested_relationship": "VARCHAR(32) NOT NULL DEFAULT ''",
            "revoked_at": "DATETIME NULL",
            "created_at": "DATETIME NULL",
            "updated_at": "DATETIME NULL",
        },
        "tool_author_keys": {
            "user_id": "INTEGER NULL",
        },
        "tool_relationship_evidence": {
            "observed_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        },
        "toolinfo_discovery": {
            "payload": f"{json_col} NULL",
        },
        "user_script_census_state": {
            "sweep_cursor": "INTEGER NOT NULL DEFAULT 0",
            # No backfill: an existing row cannot say which road it took, and
            # guessing would either strand the wikis swept from the index or
            # re-sweep the ones that were not. Blank means unknown, which the
            # sweep resolves by enumerating once and writing down what it got.
            "enumeration_source": "VARCHAR(32) NOT NULL DEFAULT ''",
        },
        "user_script_imports": {
            # Null means "no page we hold answers to that name", which is the
            # normal state for a load pointing outside the census. The resolver
            # fills it in as the pages arrive; nothing reads it as a count.
            "target_page_id": "INTEGER NULL",
            # A ResourceLoader module name, set only for the loads that name one
            # instead of a page. Blank on every row written before this existed,
            # which is the same value those rows would get if rewritten: they
            # were stored as titles, and the next sweep of each page corrects
            # them. Widening the table's unique key to include it is a migration
            # (`_widen_userscript_import_key`), not additive DDL.
            "target_module": "VARCHAR(255) NOT NULL DEFAULT ''",
        },
        # Both directory tables are deleted and rebuilt whole on every
        # projection run, so these need no backfill -- the next run writes them.
        # They still need the column to exist before that run does.
        "user_script_directory": {
            "script_id": "INTEGER NULL",
            # Rewritten whole by the next projection run, like every other
            # column here; it only has to exist before that run does.
            "created_at_wiki": "VARCHAR(32) NOT NULL DEFAULT ''",
            # Likewise rewritten whole by the next projection run.
            "touched_at_wiki": "VARCHAR(32) NOT NULL DEFAULT ''",
            # Likewise. Blank until the projection that follows the first
            # creation-date pass carrying authors, which is one run behind it.
            "first_author_wiki": "VARCHAR(255) NOT NULL DEFAULT ''",
        },
        "user_script_directory_members": {
            "script_id": "INTEGER NULL",
            "origin_id": "INTEGER NULL",
        },
        "user_script_pages": {
            # Empty until a sweep reaches the Wiki Replicas. The directory's
            # tie-break reads it as a string and falls back when it is blank, so
            # a deployment that never gets a replica connection stays correct.
            "created_at_wiki": "VARCHAR(32) NOT NULL DEFAULT ''",
            # Empty until the page is next read. An empty sketch resembles
            # nothing, so the near-copy fold simply does not fire on a row that
            # predates it -- see `proxy/migrate.py`, which fills them in from
            # the bodies already stored rather than waiting for another sweep.
            "sketch": "VARCHAR(1024) NOT NULL DEFAULT ''",
            # Empty until `backend.userscript_docs` asks the wiki whether the
            # page beside this one exists. Empty and never-asked look the same
            # in this column on purpose -- `docs_checked_at` carries that
            # difference, and NULL there is what makes an existing deployment's
            # every row pending rather than settled as undocumented.
            "docs_title": "VARCHAR(512) NOT NULL DEFAULT ''",
            "docs_checked_at": "DATETIME NULL",
            # Empty until the creation-date lane reaches the replicas again.
            # Rows dated before authors were read keep their date and acquire a
            # name on the next pass, which is why that lane asks for pages
            # missing either field rather than only for undated ones.
            "first_author_wiki": "VARCHAR(255) NOT NULL DEFAULT ''",
        },
        "wiki_gadgets": {
            # Empty until a census reaches the Wiki Replicas, exactly as for
            # `user_script_pages` above: a deployment that never gets a replica
            # connection publishes no gadget creation dates and nothing else
            # changes.
            "created_at_wiki": "VARCHAR(32) NOT NULL DEFAULT ''",
            # Empty until a census reaches the Wiki Replicas, on the same terms:
            # a gadget with no last-edit date publishes no `modified_date` and
            # simply sorts as unknown, rather than being dated from the day this
            # catalogue happened to read the wiki.
            "touched_at_wiki": "VARCHAR(32) NOT NULL DEFAULT ''",
            # Empty until a census reaches the replicas again. A gadget record
            # published before this column existed carried no author at all, so
            # filling it in only ever adds attribution and never revises one.
            "first_author_wiki": "VARCHAR(255) NOT NULL DEFAULT ''",
            # The gadget's own description message, reduced to plain text.
            # Nullable rather than NOT NULL DEFAULT '': adding it to a populated
            # table must not claim every existing row was read and found to say
            # nothing. The first census pass after this fills it.
            "description": f"{text_col} NULL",
        },
        "tool_inference": {
            # What the model actually replied, kept where the reply was refused.
            # Nullable on the same terms as `wiki_gadgets.description`: 4,260
            # rows were stored before this column existed and none of them kept
            # the reply, so NULL means "nobody wrote it down" and an empty
            # string means "asked, and nothing was refused". The sweep uses that
            # difference to find the rows worth asking about once more.
            "reply": f"{text_col} NULL",
        },
        "job_runs": {
            # The summary the job printed for this run. Nullable because the row
            # is written by the guard, which only learns the summary if the
            # child lived long enough to hand it over -- and because every run
            # recorded before that handoff existed has none.
            "summary": f"{json_col} NULL",
        },
        "repository_analysis_state": {
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            # Nullable with no default, deliberately: every existing row starts
            # as "not yet looked for", and a DEFAULT would silently declare
            # several thousand not-yet-read tools assistant-free.
            "llm_assisted": "BOOLEAN NULL",
            "llm_provider": "VARCHAR(32) NOT NULL DEFAULT ''",
            "llm_model": "VARCHAR(128) NOT NULL DEFAULT ''",
            "llm_checked_at": "DATETIME NULL",
        },
        "person_reconciliation_queue": {
            "attempts": "INTEGER NOT NULL DEFAULT 0",
        },
        "person_reconciliation_mappings": {
            "evidence": f"{json_col} NULL",
            "reviewed_by_user_id": "INTEGER NULL",
            "reviewed_at": "DATETIME NULL",
            "review_notes": f"{text_col} NULL",
            "updated_at": "DATETIME NULL",
        },
        "person_reconciliation_conflicts": {
            "status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
            "reviewed_by_user_id": "INTEGER NULL",
            "reviewed_at": "DATETIME NULL",
            "review_notes": f"{text_col} NULL",
            "last_seen_at": "DATETIME NULL",
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
    """Apply idempotent additive DDL for existing deployments.

    DDL only, deliberately. This runs from init_schema() on every worker
    start, so anything proportional to table size runs once per process on
    every restart — with several workers starting at once, against a table a
    live request needs. Row-level migrations belong in proxy/migrate.py, which
    the deploy runs once before the restart.
    """
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
                conn.exec_driver_sql(
                    f"UPDATE {table} SET attempts = 0 WHERE attempts IS NULL"  # noqa: S608 - fixed allowlist
                )


def configure(url: str) -> None:
    """Create (or replace) the process-wide engine and session factory."""
    global _engine, _session_factory  # noqa: PLW0603 — module-level singleton by design
    if _engine is not None:
        _engine.dispose()
    if url in {"sqlite://", "sqlite:///:memory:"}:
        # In-memory SQLite: share the one database across connections/threads.
        _engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        # Bounded on purpose. ToolsDB allows 20 connections per tool account, and
        # SQLAlchemy's defaults (5 pooled + 10 overflow) are per process — with
        # four webservice workers that is up to 60, so under load the pool would
        # hand out connections the database then refuses. Keep every worker's
        # ceiling low enough that the whole webservice fits in the budget with
        # room left for the scheduled jobs, which connect from their own pods.
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=POOL_SIZE_PER_WORKER,
            max_overflow=POOL_OVERFLOW_PER_WORKER,
            pool_recycle=POOL_RECYCLE_SECONDS,
            pool_timeout=POOL_TIMEOUT_SECONDS,
        )
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)


def engine() -> Engine:
    """Return the configured engine (configure() must have run)."""
    if _engine is None:
        msg = "backend.db.configure() has not been called"
        raise RuntimeError(msg)
    return _engine


# MariaDB's errno for a CREATE TABLE whose name is already taken.
# ``create_all`` asks whether each table exists and creates the ones that do
# not, but the question and the CREATE are two statements: two jobs starting in
# the same second both see a table missing and both try to make it. The loser
# gets this, and since ``create_all`` issues one statement per table, it gives
# up with the rest of the schema still uncreated.
TABLE_EXISTS_ERRNO = 1050
# One retry settles any number of tables lost to that race, because the retry
# skips everything that now exists. A second is only reachable if a third job is
# still creating tables, and stopping there keeps a genuinely broken CREATE from
# looping.
SCHEMA_CREATE_ATTEMPTS = 2


def _is_table_exists_error(error: BaseException) -> bool:
    """Say whether the database refused a CREATE because the table is there."""
    original = getattr(error, "orig", None)
    args = getattr(original, "args", ()) if original is not None else ()
    return bool(args) and args[0] == TABLE_EXISTS_ERRNO


def _create_missing_tables() -> None:
    """Create absent tables, treating a concurrent creator as the success it is.

    people-reconcile-incremental lost two runs on 2026-08-21 this way. Nothing
    was wrong when it happened: the table existed, which is the entire outcome
    this function wants, and only the job that asked second was told no. Looking
    again is the right answer, where failing the run discards a whole reconcile
    pass over a race that had already resolved itself.
    """
    for attempt in range(SCHEMA_CREATE_ATTEMPTS):
        try:
            Base.metadata.create_all(engine())
        except SQLAlchemyError as error:
            if attempt == SCHEMA_CREATE_ATTEMPTS - 1 or not _is_table_exists_error(error):
                raise
        else:
            return


def init_schema() -> None:
    """Create any missing tables (idempotent; see docs/RUNBOOK.md for changes)."""
    _create_missing_tables()
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
        acquired = (
            connection.scalar(
                text("SELECT GET_LOCK(:name, :timeout)"),
                {"name": name, "timeout": max(0, int(timeout_seconds))},
            )
            == 1
        )
        yield acquired
    finally:
        try:
            if acquired:
                connection.scalar(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
        except SQLAlchemyError:
            # MariaDB releases connection-scoped locks automatically when an
            # idle connection is reset. A failed explicit release after a
            # successful long-running job must not turn that job into a
            # reported failure.
            connection.invalidate()
        connection.close()


def advisory_lock_holder(name: str) -> int | None:
    """Return the connection id holding ``name``, or None if nobody does.

    Best effort in every direction, because this only ever runs on the failure
    path of a job that is about to skip: a lock whose holder cannot be named is
    still held, and the caller's report is worth strictly more with a missing
    field than it is not written at all. IS_USED_LOCK needs its own connection,
    which is why the answer can be stale the instant it is read -- it says who
    held the lock during the skip, not who holds it now, and that is the
    question worth answering.
    """
    if engine().dialect.name not in {"mysql", "mariadb"}:
        return None
    try:
        with engine().connect() as connection:
            holder = connection.scalar(text("SELECT IS_USED_LOCK(:name)"), {"name": name})
    except SQLAlchemyError:
        return None
    return int(holder) if holder is not None else None


# MariaDB rolls one transaction back to break a lock cycle (1213) or gives up
# waiting for a lock (1205). Both mean "your work was undone, try again", not
# "your work was wrong", and both are routine when several bounded jobs touch
# the shared identity tables in the same minute. Retrying is the documented
# remedy; without it a scheduled sweep loses a whole run to a collision that
# resolves itself in milliseconds.
TRANSIENT_LOCK_ERRNOS = (1205, 1213)
DEFAULT_LOCK_RETRIES = 3
LOCK_RETRY_BACKOFF_SECONDS = 0.2


def is_transient_lock_error(error: BaseException) -> bool:
    """Return True when the database undid the work and inviting a retry."""
    original = getattr(error, "orig", None)
    args = getattr(original, "args", ()) if original is not None else ()
    return bool(args) and args[0] in TRANSIENT_LOCK_ERRNOS


def run_with_lock_retry(
    work: Callable[[], T],
    *,
    attempts: int = DEFAULT_LOCK_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run one unit of work again when the database rolled it back for a lock.

    ``work`` must own its transaction and be safe to repeat, which is why this
    wraps a whole session_scope() rather than living inside one: by the time
    the error surfaces the transaction is already gone.
    """
    last: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            return work()
        except SQLAlchemyError as error:
            if not is_transient_lock_error(error):
                raise
            last = error
            if attempt < attempts - 1:
                sleep(LOCK_RETRY_BACKOFF_SECONDS * (attempt + 1))
    # Every attempt lost the same race; surface the database's own error.
    raise last


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
