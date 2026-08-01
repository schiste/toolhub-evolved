# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLAlchemy models for Evolved-owned data and bounded public caches.

Most rows are complementary records: user accounts, local deltas, verification
claims, and activity. `CanonicalToolCache` is the deliberate exception: it is a
structured public cache of official Toolhub tool records, used for fast fallback
reads while live Toolhub data is stale or unavailable.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_UNVERIFIED,
    REVIEW_APPROVED,
    REVIEW_OPEN,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SOURCE_OFFICIAL,
    SYNC_EVOLVED_REAL,
    SYNC_LOCAL_DRAFT,
    SYNC_OFFICIAL,
)

# Bound on the denormalized canonical search haystack (see CanonicalToolCache).
SEARCH_TEXT_MAX_CHARS = 4000


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
    role: Mapped[str] = mapped_column(String(32), default="user")
    # Bumped on sign-out to invalidate every session cookie already issued to
    # this user. Flask sessions are signed client-side cookies, so without a
    # server-side counter a stolen cookie stays valid for its full lifetime.
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
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


class ApiCache(Base):
    """Anonymous Toolhub GET response or bounded derived public payload.

    `path`/`collection`/`detail_key` are the URL decomposition invalidation
    matches on. They are stored (rather than re-derived from `url` at read time)
    so invalidation is an indexed DELETE instead of a full-table scan that would
    have to materialize every `body` blob just to inspect its URL.
    """

    __tablename__ = "api_cache"
    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    # Normalized upstream path, always with a trailing slash (e.g. "/api/tools/").
    path: Mapped[str] = mapped_column(String(512), default="", index=True)
    # Decoded second path segment for /api/ URLs ("tools", "lists", …), else "".
    collection: Mapped[str] = mapped_column(String(64), default="", index=True)
    # Decoded third path segment: the tool name or list id, else "".
    detail_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    status: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(255), default="application/json")
    body: Mapped[bytes] = mapped_column(LargeBinary(length=10 * 1024 * 1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    stale_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApiCacheMeta(Base):
    """Small persistent state used by the anonymous Toolhub API cache."""

    __tablename__ = "api_cache_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CanonicalToolCache(Base):
    """Structured local cache of canonical official Toolhub tool records."""

    __tablename__ = "canonical_tool_cache"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    record: Mapped[dict] = mapped_column(JSON, default=dict)
    # Lowercased name/title/description, denormalized out of `record` so a search
    # can filter and limit in SQL. Matching inside the JSON column would mean
    # shipping every record to Python to test a substring.
    search_text: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(String(2000), default="")
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    stale_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @validates("record")
    def _derive_search_text(self, _key: str, record: dict | None) -> dict | None:
        """Keep search_text in step with record on every assignment.

        Deriving it here rather than at the call site means a row inserted by
        any path is searchable; a caller that forgot would otherwise write a
        row that simply never matches, with nothing to indicate why.
        """
        source = record or {}
        parts = (source.get("name"), source.get("title"), source.get("description"))
        self.search_text = "\n".join(str(part or "") for part in parts).casefold()[:SEARCH_TEXT_MAX_CHARS]
        return record


class GraphToolEnrichment(Base):
    """Versioned, provenance-aware facets derived for the public tool graph."""

    __tablename__ = "graph_tool_enrichment"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    facets: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    source_timestamps: Mapped[dict] = mapped_column(JSON, default=dict)
    enrichment_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CatalogToolProjection(Base):
    """Versioned Evolved-local catalog view assembled from public evidence."""

    __tablename__ = "catalog_tool_projection"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    effective_record: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    source_timestamps: Mapped[dict] = mapped_column(JSON, default=dict)
    search_text: Mapped[str] = mapped_column(Text, default="")
    projection_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CatalogCuration(Base):
    """One reviewed local correction proposed for an official catalog tool."""

    __tablename__ = "catalog_curations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    patch: Mapped[dict] = mapped_column(JSON, default=dict)
    lifecycle_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(32), default=REVIEW_PENDING, index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)


class CatalogFacetValue(Base):
    """Indexed normalized facet value materialized from one catalog projection."""

    __tablename__ = "catalog_facet_values"
    __table_args__ = (UniqueConstraint("tool_name", "field", "value"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    field: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(String(255), index=True)
    label: Mapped[str] = mapped_column(String(255), default="")
    provenance: Mapped[list] = mapped_column(JSON, default=list)
    confidence_basis_points: Mapped[int] = mapped_column(Integer, default=10000)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolAssetCache(Base):
    """Rebuildable metadata for one safely cached public tool asset."""

    __tablename__ = "tool_asset_cache"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(2000), default="")
    source_type: Mapped[str] = mapped_column(String(64), default="official_toolhub")
    content_type: Mapped[str] = mapped_column(String(255), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    cached_path: Mapped[str] = mapped_column(String(512), default="")
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolCatalogSyncState(Base):
    """Resumable cursor and health state for the complete official catalog sync."""

    __tablename__ = "tool_catalog_sync_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_page: Mapped[int] = mapped_column(Integer, default=1)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    cycles_completed: Mapped[int] = mapped_column(Integer, default=0)
    reconcile_next_page: Mapped[int] = mapped_column(Integer, default=1)
    reconcile_cycles_completed: Mapped[int] = mapped_column(Integer, default=0)
    reconcile_last_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recent_latest_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recent_pending_tools: Mapped[list] = mapped_column(JSON, default=list)
    recent_last_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detail_hydration_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail_hydration_pending_tools: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)


class MaintainerBackfillState(Base):
    """Resumable state for the paced Toolsadmin maintainer backfill."""

    __tablename__ = "maintainer_backfill_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tools_checked: Mapped[int] = mapped_column(Integer, default=0)
    maintainers_found: Mapped[int] = mapped_column(Integer, default=0)
    failed_tools: Mapped[int] = mapped_column(Integer, default=0)
    cycles_completed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolOwnerCache(Base):
    """Derived owner label cache for recent-change tool rows."""

    __tablename__ = "tool_owner_cache"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(64), default="toolhub_detail")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    stale_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolSummaryCache(Base):
    """Materialized public health + maintainer summary for one tool."""

    __tablename__ = "tool_summary_cache"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    stale_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserToolResolverCache(Base):
    """Private last-known resolver result for one Toolhub user."""

    __tablename__ = "user_tool_resolver_cache"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    stale_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IssueReport(Base):
    """Idempotency ledger for issues published from the authenticated drawer."""

    __tablename__ = "issue_reports"
    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    repository: Mapped[str] = mapped_column(String(255))
    issue_number: Mapped[int] = mapped_column(Integer)
    issue_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Favorite(Base):
    """One favorited tool name for one user."""

    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "tool_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
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
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
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
    last_toolhub_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolRecord(Base):
    """A net-new tool registered on this site (never an upstream mirror)."""

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tool_name", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    record: Mapped[dict] = mapped_column(JSON, default=dict)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    official_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), default="private")
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_LOCAL_DRAFT)
    review_status: Mapped[str] = mapped_column(String(32), default=REVIEW_PENDING)
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
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    patch: Mapped[dict] = mapped_column(JSON, default=dict)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    base_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    field_statuses: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_LOCAL_DRAFT)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_toolhub_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default=REVIEW_OPEN)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ActivityRow(Base):
    """One revision-or-audit feed row (kind: "revisions" | "auditlogs")."""

    __tablename__ = "activity"
    __table_args__ = (UniqueConstraint("kind", "client_id"),)  # feed rows are global — one row per client id
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    row: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    object_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    official_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CrawlerUrl(Base):
    """A toolinfo.json URL a user registered for the server-side crawler."""

    __tablename__ = "crawler_urls"
    __table_args__ = (UniqueConstraint("user_id", "url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    url: Mapped[str] = mapped_column(String(2000))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    official_crawler_url_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_toolhub_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
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


class ToolinfoDiscovery(Base):
    """Cached discovery state for an official Toolhub tool's toolinfo.json."""

    __tablename__ = "toolinfo_discovery"
    __table_args__ = (UniqueConstraint("tool_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    tool_url: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    toolinfo_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    tool_names: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[list] = mapped_column(JSON, default=list)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)


class ToolinfoDiscoveryMeta(Base):
    """Small persistent state for the automated toolinfo discovery job."""

    __tablename__ = "toolinfo_discovery_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolinfoSource(Base):
    """Official Toolhub crawler URL indexed locally as source evidence."""

    __tablename__ = "toolinfo_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    official_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    url: Mapped[str] = mapped_column(String(2000), unique=True, index=True)
    source_kind: Mapped[str] = mapped_column(String(64), default="registered_toolinfo")
    created_by_username: Mapped[str] = mapped_column(String(255), default="")
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)


class ToolinfoSourceItem(Base):
    """One tool name observed in an official Toolhub crawler feed."""

    __tablename__ = "toolinfo_source_items"
    __table_args__ = (UniqueConstraint("tool_name", "source_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("toolinfo_sources.id"), index=True)
    source_url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(255), default="")
    tool_url: Mapped[str] = mapped_column(String(2000), default="")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)


class ToolEvent(Base):
    """Privacy-limited interaction event used for Evolved aggregate metrics."""

    __tablename__ = "tool_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    event_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolThanks(Base):
    """One active Evolved thanks relation per user/tool."""

    __tablename__ = "tool_thanks"
    __table_args__ = (UniqueConstraint("tool_name", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    review_status: Mapped[str] = mapped_column(String(32), default=REVIEW_APPROVED)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolAuthorClaim(Base):
    """Per-tool proof state for a Toolhub author name claimed by a Toolhub user."""

    __tablename__ = "tool_author_claims"
    __table_args__ = (UniqueConstraint("tool_name", "author_name", "toolhub_username", "verification_method"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    author_name: Mapped[str] = mapped_column(String(255), index=True)
    toolhub_username: Mapped[str] = mapped_column(String(255), index=True)
    verification_status: Mapped[str] = mapped_column(String(32), default=AUTHOR_CLAIM_UNVERIFIED)
    verification_method: Mapped[str] = mapped_column(String(64), default=AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME)
    evidence_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolAuthorKey(Base):
    """A public key a Toolhub user registered for signed toolinfo ownership proofs."""

    __tablename__ = "tool_author_keys"
    __table_args__ = (UniqueConstraint("toolhub_username", "key_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    toolhub_username: Mapped[str] = mapped_column(String(255), index=True)
    key_id: Mapped[str] = mapped_column(String(128), index=True)
    public_key: Mapped[str] = mapped_column(Text)
    algorithm: Mapped[str] = mapped_column(String(32), default="ed25519")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolMaintainerEdge(Base):
    """Derived per-tool maintainer edge with provenance and confidence."""

    __tablename__ = "tool_maintainer_edges"
    __table_args__ = (UniqueConstraint("tool_name", "maintainer_key", "source", "method"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    maintainer_key: Mapped[str] = mapped_column(String(255), index=True)
    maintainer_display_name: Mapped[str] = mapped_column(String(255), default="")
    toolhub_username: Mapped[str] = mapped_column(String(255), default="", index=True)
    wiki_username: Mapped[str] = mapped_column(String(255), default="", index=True)
    author_name: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(64), default=SOURCE_LOCAL)
    method: Mapped[str] = mapped_column(String(64), default=AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME)
    verification_status: Mapped[str] = mapped_column(String(32), default=AUTHOR_CLAIM_UNVERIFIED)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaintainerActivityRollup(Base):
    """Derived local activity rollup for one maintainer identity."""

    __tablename__ = "maintainer_activity_rollups"
    maintainer_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    maintainer_display_name: Mapped[str] = mapped_column(String(255), default="")
    toolhub_username: Mapped[str] = mapped_column(String(255), default="", index=True)
    source: Mapped[str] = mapped_column(String(64), default=SOURCE_LOCAL)
    maintainer_count_hint: Mapped[int] = mapped_column(Integer, default=1)
    active_tool_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_tool_count: Mapped[int] = mapped_column(Integer, default=0)
    recent_activity_count: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity_status: Mapped[str] = mapped_column(String(32), default="unknown")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Person(Base):
    """A deduplicated person identity shared across tool relationships."""

    __tablename__ = "people"
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    identity_quality: Mapped[str] = mapped_column(String(32), default="display_name")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonIdentifier(Base):
    """A stable external identifier attached to one person."""

    __tablename__ = "person_identifiers"
    __table_args__ = (UniqueConstraint("namespace", "normalized_value"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    namespace: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(255))
    normalized_value: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolPersonRelationship(Base):
    """Evidence-backed role relationship between one tool and one person."""

    __tablename__ = "tool_person_relationships"
    __table_args__ = (UniqueConstraint("tool_name", "person_id", "relationship_type", "source", "method"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), default=SOURCE_LOCAL)
    method: Mapped[str] = mapped_column(String(64), default=AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME)
    verification_status: Mapped[str] = mapped_column(String(32), default=AUTHOR_CLAIM_UNVERIFIED)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonReconciliationRun(Base):
    """Audited deterministic identity reconciliation run."""

    __tablename__ = "person_reconciliation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), default="dry-run")
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PersonReconciliationMapping(Base):
    """One proposed or applied canonical-person mapping."""

    __tablename__ = "person_reconciliation_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("person_reconciliation_runs.id"), index=True)
    source_person_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target_person_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_key: Mapped[str] = mapped_column(String(255), default="")
    target_key: Mapped[str] = mapped_column(String(255), default="")
    decision: Mapped[str] = mapped_column(String(32), default="candidate")
    reason: Mapped[str] = mapped_column(String(128), default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonReconciliationConflict(Base):
    """An ambiguity intentionally left unresolved by reconciliation."""

    __tablename__ = "person_reconciliation_conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("person_reconciliation_runs.id"), index=True)
    person_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    conflict_type: Mapped[str] = mapped_column(String(64), default="")
    value: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonReconciliationQueue(Base):
    """Deduplicated tool work awaiting incremental people reconciliation."""

    __tablename__ = "person_reconciliation_queue"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    reason: Mapped[str] = mapped_column(String(64), default="data_ingestion")
    enqueued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceAnalysisReport(Base):
    """Derived source-code metadata suggestions owned by one signed-in user."""

    __tablename__ = "source_analysis_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    source_label: Mapped[str] = mapped_column(String(255), default="")
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(32), default=REVIEW_OPEN)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)


class RepositoryAnalysisState(Base):
    """Incremental state for deterministic scans of public tool repositories."""

    __tablename__ = "repository_analysis_state"
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    repository_url: Mapped[str] = mapped_column(String(2000), default="")
    provider: Mapped[str] = mapped_column(String(64), default="")
    commit_sha: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    report_id: Mapped[int | None] = mapped_column(ForeignKey("source_analysis_reports.id"), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)


class ToolHealthTarget(Base):
    """A URL Evolved may check to report health for one tool."""

    __tablename__ = "tool_health_targets"
    __table_args__ = (UniqueConstraint("tool_name", "created_by_user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    target_url: Mapped[str] = mapped_column(String(2000))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)
    review_status: Mapped[str] = mapped_column(String(32), default=REVIEW_PENDING)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)


class ToolMedia(Base):
    """Screenshot or preview metadata owned and moderated by Evolved."""

    __tablename__ = "tool_media"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(255), default="")
    license: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(2000), default="")
    review_status: Mapped[str] = mapped_column(String(32), default=REVIEW_PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
