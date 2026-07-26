# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLAlchemy models — the site's complementary records.

Nothing in here mirrors upstream Toolhub catalog data (docs/PRODUCTION.md §0):
rows are user accounts and the deltas users create on this site. Overlay rows
(edits/annotations) and net-new tool records are keyed by tool name and carry
the contributing user, so the assembled overlay can be rebuilt per key in the
exact shapes the SPA's localStorage cache uses.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.sync import SOURCE_LOCAL, SYNC_EVOLVED_REAL, SYNC_LOCAL_DRAFT


def utcnow() -> datetime:
    """Return the current UTC time with tzinfo stripped.

    DATETIME columns hold naive UTC on both SQLite and MariaDB; the API layer
    re-attaches the Z suffix on output.
    """
    return datetime.now(tz=UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for all Toolhub Evolved tables."""


class User(Base):
    """A Toolhub account that authorized Toolhub Evolved via OAuth."""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Historical column name: now stores the official Toolhub numeric user id as
    # a string. Keeping the DB column avoids a destructive migration on Toolforge.
    wm_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255))
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolhubToken(Base):
    """The official Toolhub OAuth grant for one local user."""

    __tablename__ = "toolhub_tokens"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(32), default="Bearer")
    scope: Mapped[str] = mapped_column(String(255), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Favorite(Base):
    """One favorited tool name for one user."""

    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "tool_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_LOCAL_DRAFT)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolList(Base):
    """A user-created list of tool names (client-generated string id)."""

    __tablename__ = "lists"
    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    official_list_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_LOCAL_DRAFT)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolRecord(Base):
    """A net-new tool registered on this site (never an upstream mirror)."""

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tool_name", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    record: Mapped[dict] = mapped_column(JSON, default=dict)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    official_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), default="private")
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_LOCAL_DRAFT)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_toolhub_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolOverlay(Base):
    """A field overlay ("edits" or "annos") one user layered on a tool."""

    __tablename__ = "tool_overlays"
    __table_args__ = (UniqueConstraint("kind", "tool_name", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    patch: Mapped[dict] = mapped_column(JSON, default=dict)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    base_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    field_statuses: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_LOCAL_DRAFT)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="open")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ActivityRow(Base):
    """One revision-or-audit feed row (kind: "revisions" | "auditlogs")."""

    __tablename__ = "activity"
    __table_args__ = (UniqueConstraint("kind", "client_id"),)  # feed rows are global — one row per client id
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    row: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    object_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    official_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CrawlerUrl(Base):
    """A toolinfo.json URL a user registered for the server-side crawler."""

    __tablename__ = "crawler_urls"
    __table_args__ = (UniqueConstraint("user_id", "url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    official_crawler_url_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_LOCAL_DRAFT)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CrawlerRun(Base):
    """One recorded run of the server-side crawler job."""

    __tablename__ = "crawler_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    urls_count: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)


class ToolEvent(Base):
    """Privacy-limited interaction event used for Evolved aggregate metrics."""

    __tablename__ = "tool_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    event_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolThanks(Base):
    """One active Evolved thanks relation per user/tool."""

    __tablename__ = "tool_thanks"
    __table_args__ = (UniqueConstraint("tool_name", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolHealthTarget(Base):
    """A URL Evolved may check to report health for one tool."""

    __tablename__ = "tool_health_targets"
    __table_args__ = (UniqueConstraint("tool_name", "created_by_user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    target_url: Mapped[str] = mapped_column(String(2000))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolHealthCheck(Base):
    """One observed health-check result for an Evolved health target."""

    __tablename__ = "tool_health_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("tool_health_targets.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolMedia(Base):
    """Screenshot or preview metadata owned and moderated by Evolved."""

    __tablename__ = "tool_media"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(255), default="")
    license: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(2000), default="")
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
