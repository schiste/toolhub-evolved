# SPDX-License-Identifier: GPL-3.0-or-later
"""Database engine + session plumbing (SQLAlchemy).

SQLite (repo-local file) in development and tests; ToolsDB (MariaDB via
PyMySQL) on Toolforge through the TOOLHUB_DB_URL env var. `configure()` may be
called again with a new URL (tests do this per-fixture) — the previous engine
is disposed.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


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
