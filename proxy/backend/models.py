# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLAlchemy models for Evolved-owned data and bounded public caches.

Most rows are complementary records: user accounts, local deltas, verification
claims, and activity. `CanonicalToolCache` is the deliberate exception: it is a
structured public cache of official Toolhub tool records, used for fast fallback
reads while live Toolhub data is stale or unavailable.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
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
DIGEST_RENDER_TEXT = Text().with_variant(MEDIUMTEXT(), "mysql").with_variant(MEDIUMTEXT(), "mariadb")

# Public catalog cards need only this stable Toolhub subset. Keeping a derived
# JSON projection avoids reading and serializing detail-only fields (and large
# multilingual/source payloads) for every browse result while the canonical
# record remains intact for detail pages and reconciliation.
CATALOG_CARD_FIELDS = (
    "name",
    "title",
    "description",
    "url",
    "icon",
    "keywords",
    "author",
    "created_by",
    "wikidata_qid",
    "subtitle",
    "sponsor",
    "replaced_by",
    "tool_type",
    "license",
    "repository",
    "api_url",
    "technology_used",
    "audiences",
    "tasks",
    "for_wikis",
    "available_ui_languages",
    "user_docs_url",
    "developer_docs_url",
    "feedback_url",
    "bugtracker_url",
    "translate_url",
    "deprecated",
    "experimental",
    "modified_date",
    "modified",
    "origin",
    "annotations",
    "_language",
)


def catalog_card_record(record: dict | None) -> dict:
    """Return the bounded canonical record shape required by list cards."""
    source = record if isinstance(record, dict) else {}
    return {field: source[field] for field in CATALOG_CARD_FIELDS if field in source}


def catalog_modified_at(record: dict | None) -> datetime | None:
    """Normalize Toolhub's modification timestamp into naive UTC for sorting."""
    source = record if isinstance(record, dict) else {}
    raw = source.get("modified_date") or source.get("modified")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def utcnow() -> datetime:
    """Return the current UTC time with tzinfo stripped.

    DATETIME columns hold naive UTC on both SQLite and MariaDB; the API layer
    re-attaches the Z suffix on output.
    """
    return datetime.now(tz=UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for all Toolhub Evolved tables."""


class ToolActivityEvent(Base):
    """One immutable official Toolhub event eligible for digest publication."""

    __tablename__ = "tool_activity_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upstream_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(32), default="created", index=True)
    event_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)


class DigestEdition(Base):
    """One immutable English publication for a closed UTC period."""

    __tablename__ = "digest_editions"
    __table_args__ = (UniqueConstraint("cadence", "period_start", "language_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cadence: Mapped[str] = mapped_column(String(16), index=True)
    edition_key: Mapped[str] = mapped_column(String(32), index=True)
    language_code: Mapped[str] = mapped_column(String(16), default="en", index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(32), default="generating", index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    introduction: Mapped[str] = mapped_column(Text, default="")
    rendered_html: Mapped[str] = mapped_column(DIGEST_RENDER_TEXT, default="")
    rendered_wikitext: Mapped[str] = mapped_column(DIGEST_RENDER_TEXT, default="")
    rendered_text: Mapped[str] = mapped_column(DIGEST_RENDER_TEXT, default="")
    source_hash: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    model_name: Mapped[str] = mapped_column(String(255), default="")
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    meta_page_title: Mapped[str] = mapped_column(String(1000), default="")
    meta_page_url: Mapped[str] = mapped_column(String(2000), default="")
    meta_revision_id: Mapped[str] = mapped_column(String(64), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DigestEditionTool(Base):
    """Frozen source facts and validated editorial copy for one edition tool."""

    __tablename__ = "digest_edition_tools"
    __table_args__ = (UniqueConstraint("edition_id", "event_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("digest_editions.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("tool_activity_events.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    highlighted: Mapped[bool] = mapped_column(Boolean, default=False)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    blurb: Mapped[str] = mapped_column(Text, default="")


class DigestSubscription(Base):
    """One signed-in user's opt-in for a push digest channel and cadence."""

    __tablename__ = "digest_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "channel", "cadence", "wiki_domain", "language_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16), index=True)
    cadence: Mapped[str] = mapped_column(String(16), index=True)
    language_code: Mapped[str] = mapped_column(String(16), default="en")
    wiki_domain: Mapped[str] = mapped_column(String(255), default="meta.wikimedia.org")
    wiki_username: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DigestDelivery(Base):
    """Idempotent, retryable delivery of an edition to one subscription."""

    __tablename__ = "digest_deliveries"
    __table_args__ = (UniqueConstraint("edition_id", "subscription_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("digest_editions.id"), index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("digest_subscriptions.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    external_id: Mapped[str] = mapped_column(String(255), default="")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DigestGenerationAttempt(Base):
    """Auditable outcome of one model or deterministic generation attempt."""

    __tablename__ = "digest_generation_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("digest_editions.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    model_name: Mapped[str] = mapped_column(String(255), default="")
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DigestOperationalState(Base):
    """Durable health of a singleton digest publication component."""

    __tablename__ = "digest_operational_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    """A Toolhub account that authorized Toolhub Evolved via OAuth."""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Historical column name: now stores the official Toolhub numeric user id as
    # a string. Keeping the DB column avoids a destructive migration on Toolforge.
    wm_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255))
    # Stable CentralAuth identity returned by Toolhub's Wikimedia social-auth
    # binding. Unlike the username, this survives account renames.
    wikimedia_global_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # A signed-in account and a public person are deliberately separate. Some
    # people never sign in, while one authenticated Toolhub account can be
    # linked deterministically through its immutable numeric upstream id.
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), nullable=True, unique=True, index=True)
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
    # Nullable only for the deploy window in which an existing table has gained
    # the column but migrate.py has not completed its bounded backfill yet.
    card_record: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    # Lowercased name/title/description, denormalized out of `record` so a search
    # can filter and limit in SQL. Matching inside the JSON column would mean
    # shipping every record to Python to test a substring.
    search_text: Mapped[str] = mapped_column(Text, default="")
    modified_at_sort: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(String(2000), default="")
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    stale_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full catalog snapshots mark every observed row with one generation.
    # Rows from older generations are pruned only after the new snapshot has
    # fetched every page and matched Toolhub's advertised distinct count.
    generation: Mapped[int] = mapped_column(Integer, default=0, index=True)

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
        self.card_record = catalog_card_record(source)
        self.modified_at_sort = catalog_modified_at(source)
        return record


class CatalogSnapshotStage(Base):
    """Unpublished rows for one consistency-checked full catalog generation."""

    __tablename__ = "catalog_snapshot_stage"
    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    record: Mapped[dict] = mapped_column(JSON, default=dict)
    source_url: Mapped[str] = mapped_column(String(2000), default="")
    staged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolhubAccountProjection(Base):
    """Rebuildable public projection of one official Toolhub account.

    This is intentionally separate from ``User``. A projection row means the
    account exists upstream; a User row means that account authorized Evolved.
    Neither fact implies contribution activity or grants local permissions.
    """

    __tablename__ = "toolhub_account_projection"
    toolhub_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(255))
    normalized_username: Mapped[str] = mapped_column(String(255), default="", index=True)
    groups: Mapped[list] = mapped_column(JSON, default=list)
    groups_search: Mapped[str] = mapped_column(String(1000), default="", index=True)
    wikimedia_global_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    wikimedia_registered_at: Mapped[str] = mapped_column(String(32), default="")
    date_joined: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(String(2000), default="")
    generation: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolhubAccountSyncState(Base):
    """Resumable generation state for the official Toolhub account mirror."""

    __tablename__ = "toolhub_account_sync_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_page: Mapped[int] = mapped_column(Integer, default=1)
    active_generation: Mapped[int] = mapped_column(Integer, default=0)
    cycle_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cycles_completed: Mapped[int] = mapped_column(Integer, default=0)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    cycle_records_seen: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)


class ToolforgeAccountProjection(Base):
    """Rebuildable projection of one Wikimedia developer account.

    ``uid_number`` is the immutable LDAP/POSIX identifier. ``uid`` is the
    Unix shell login while ``developer_username`` is LDAP ``cn``: the
    Wikimedia Developer account name used by toolinfo's
    ``author.developer_username``. Neither handle may identify a person on its
    own. The Wikimedia binding is nullable because many legacy developer
    accounts have not connected their SUL identity.
    """

    __tablename__ = "toolforge_account_projection"
    uid_number: Mapped[str] = mapped_column(String(64), primary_key=True)
    uid: Mapped[str] = mapped_column(String(255), index=True)
    normalized_uid: Mapped[str] = mapped_column(String(255), default="", index=True)
    developer_username: Mapped[str] = mapped_column(String(255), default="", index=True)
    normalized_developer_username: Mapped[str] = mapped_column(String(255), default="", index=True)
    wikimedia_global_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    wikimedia_global_name: Mapped[str] = mapped_column(String(255), default="")
    ldap_created_at: Mapped[str] = mapped_column(String(32), default="")
    # Store capability, not credentials. Verification re-reads the current
    # public keys from LDAP so removed/rotated keys cannot survive in cache.
    ssh_key_count: Mapped[int] = mapped_column(Integer, default=0)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolforgeMembershipProjection(Base):
    """One current Toolforge tool-account membership for a developer account."""

    __tablename__ = "toolforge_membership_projection"
    uid_number: Mapped[str] = mapped_column(ForeignKey("toolforge_account_projection.uid_number"), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PhabricatorProfileProjection(Base):
    """Cached public ``username -> real name`` pair for one Phabricator handle.

    Read from ``/p/<username>/``, which is the only anonymous direction the
    site offers. The row is keyed on the Phabricator handle rather than on any
    Toolforge identifier because it caches a *read*, not a link: which account
    a pair may identify is re-decided by policy on every sweep, so a changed
    LDAP mirror cannot leave a stale identity behind this cache.

    ``real_name`` is empty for a handle whose profile carries no real name and
    for a handle Phabricator does not know. Both are ordinary outcomes and are
    stored so the sweep does not re-request them every cycle; ``missing``
    separates the two for operators.
    """

    __tablename__ = "phabricator_profile_projection"
    normalized_username: Mapped[str] = mapped_column(String(255), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    real_name: Mapped[str] = mapped_column(String(255), default="")
    normalized_real_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    missing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="phabricator_profile")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolforgeAccountSyncState(Base):
    """Generation state for the authoritative LDAP account/membership mirror."""

    __tablename__ = "toolforge_account_sync_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_generation: Mapped[int] = mapped_column(Integer, default=0)
    cycles_completed: Mapped[int] = mapped_column(Integer, default=0)
    accounts_seen: Mapped[int] = mapped_column(Integer, default=0)
    memberships_seen: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)


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
    __table_args__ = (
        UniqueConstraint("tool_name", "field", "value"),
        # Aggregate queries group in field/value order, then count distinct
        # tools. The legacy unique index starts with tool_name and forces
        # MariaDB into a temporary table + filesort for every request.
        Index("ix_catalog_facet_values_field_value_tool", "field", "value", "tool_name"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255))
    field: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(255))
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
    snapshot_generation: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_next_page: Mapped[int] = mapped_column(Integer, default=1)
    snapshot_expected_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recent_latest_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recent_pending_tools: Mapped[list] = mapped_column(JSON, default=list)
    recent_scan_page: Mapped[int] = mapped_column(Integer, default=1)
    recent_scan_latest_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recent_scan_boundary_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recent_cursor_recovery_required: Mapped[bool] = mapped_column(Boolean, default=False)
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


class JobRun(Base):
    """One scheduled-job invocation that actually executed its child command.

    Deliberately not a log of every tick. A skipped overlap is routine and
    would bury the signal under thousands of rows a day; what matters is when
    a job last really ran, which is exactly what silently stopped being true
    for ten days when a killed run leaked its guard lock.
    """

    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    exit_code: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


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
    skipped: Mapped[list] = mapped_column(JSON, default=list)  # healthy no-ops; never affects `ok`
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_LOCAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_EVOLVED_REAL)


class ToolinfoControlChallenge(Base):
    """A short-lived proof that an account can change one toolinfo URL."""

    __tablename__ = "toolinfo_control_challenges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    toolinfo_url: Mapped[str] = mapped_column(String(2000))
    challenge_token: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class ToolinfoSourceGeneration(Base):
    """One completed fetch of an official toolinfo source.

    Item rows intentionally remain a last-good projection.  Generations are
    the audit trail that proves which complete document produced that
    projection without making a failed fetch an authoritative deletion.
    """

    __tablename__ = "toolinfo_source_generations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("toolinfo_sources.id"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(32), default=SOURCE_OFFICIAL)
    sync_status: Mapped[str] = mapped_column(String(32), default=SYNC_OFFICIAL)


class ToolinfoSourceAttestation(Base):
    """Current generic control classification for one indexed feed."""

    __tablename__ = "toolinfo_source_attestations"
    source_id: Mapped[int] = mapped_column(ForeignKey("toolinfo_sources.id"), primary_key=True)
    classification: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    status: Mapped[str] = mapped_column(String(32), default="unverified", index=True)
    controller_person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), nullable=True, index=True)
    controller_count: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(64), default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolinfoAuthorBinding(Base):
    """Source-scoped binding from an author token to one stable person."""

    __tablename__ = "toolinfo_author_bindings"
    __table_args__ = (UniqueConstraint("source_id", "normalized_label"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("toolinfo_sources.id"), index=True)
    normalized_label: Mapped[str] = mapped_column(String(255), index=True)
    observed_label: Mapped[str] = mapped_column(String(255), default="")
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="unresolved", index=True)
    method: Mapped[str] = mapped_column(String(64), default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
    """Account-owned workflow state for one requested person/tool relationship."""

    __tablename__ = "tool_author_claims"
    __table_args__ = (
        UniqueConstraint("tool_name", "author_name", "toolhub_username", "verification_method"),
        UniqueConstraint("tool_name", "author_name", "user_id", "verification_method"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    author_name: Mapped[str] = mapped_column(String(255), index=True)
    toolhub_username: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    verification_status: Mapped[str] = mapped_column(String(32), default=AUTHOR_CLAIM_UNVERIFIED)
    verification_method: Mapped[str] = mapped_column(String(64), default=AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME)
    requested_relationship: Mapped[str] = mapped_column(String(32), default="", index=True)
    evidence_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolAuthorKey(Base):
    """A public key a Toolhub user registered for signed toolinfo ownership proofs."""

    __tablename__ = "tool_author_keys"
    __table_args__ = (UniqueConstraint("toolhub_username", "key_id"), UniqueConstraint("user_id", "key_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    toolhub_username: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    key_id: Mapped[str] = mapped_column(String(128), index=True)
    public_key: Mapped[str] = mapped_column(Text)
    algorithm: Mapped[str] = mapped_column(String(32), default="ed25519")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Person(Base):
    """A deduplicated person identity shared across tool relationships."""

    __tablename__ = "people"
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=lambda: str(uuid4()))
    public_slug: Mapped[str | None] = mapped_column(String(96), unique=True, index=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    identity_quality: Mapped[str] = mapped_column(String(32), default="display_name")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonIdentifier(Base):
    """An external stable id or mutable handle attached to one person."""

    __tablename__ = "person_identifiers"
    __table_args__ = (UniqueConstraint("namespace", "normalized_value"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    namespace: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(255))
    normalized_value: Mapped[str] = mapped_column(String(255))
    identifier_kind: Mapped[str] = mapped_column(String(32), default="handle", index=True)
    source: Mapped[str] = mapped_column(String(64), default=SOURCE_LOCAL)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonAccountBinding(Base):
    """Audited proof that one immutable provider account belongs to a person."""

    __tablename__ = "person_account_bindings"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    proof_method: Mapped[str] = mapped_column(String(64), default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccountLinkChallenge(Base):
    """Short-lived single-use proof challenge for reconnecting an account."""

    __tablename__ = "account_link_challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    challenge_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonProfile(Base):
    """Evolved-owned public profile content for a resolved person."""

    __tablename__ = "person_profiles"
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), primary_key=True)
    bio: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(String(2000), default="")
    website_url: Mapped[str] = mapped_column(String(2000), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    links: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(32), default="public", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolRelationshipEvidence(Base):
    """One provenance observation supporting a typed person/tool relationship."""

    __tablename__ = "tool_relationship_evidence"
    __table_args__ = (
        UniqueConstraint("tool_name", "person_id", "relationship_type", "source", "method", "evidence_key"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), default=SOURCE_LOCAL, index=True)
    method: Mapped[str] = mapped_column(String(64), default=AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME)
    evidence_key: Mapped[str] = mapped_column(String(255), default="")
    observed_name: Mapped[str] = mapped_column(String(255), default="")
    verification_status: Mapped[str] = mapped_column(String(32), default=AUTHOR_CLAIM_UNVERIFIED)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    # True only when the observation is a projection of canonical Toolhub
    # catalog data. It never implies Evolved owns that upstream fact.
    toolhub_canonical: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    evidence_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UnresolvedAttributionEvidence(Base):
    """A relationship observation whose label is not a proven person identity."""

    __tablename__ = "unresolved_attribution_evidence"
    __table_args__ = (
        UniqueConstraint("tool_name", "normalized_label", "relationship_type", "source", "method", "evidence_key"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    observed_label: Mapped[str] = mapped_column(String(255), default="")
    normalized_label: Mapped[str] = mapped_column(String(255), index=True)
    relationship_type: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(64), default="")
    evidence_key: Mapped[str] = mapped_column(String(255), default="")
    verification_status: Mapped[str] = mapped_column(String(32), default=AUTHOR_CLAIM_UNVERIFIED)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    toolhub_canonical: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    evidence_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolPersonRelationship(Base):
    """One resolved current role between a tool and a person."""

    __tablename__ = "person_tool_relationships"
    __table_args__ = (UniqueConstraint("tool_name", "person_id", "relationship_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(32), index=True)
    verification_status: Mapped[str] = mapped_column(String(32), default=AUTHOR_CLAIM_UNVERIFIED)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    toolhub_canonical: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonActivitySummary(Base):
    """Rebuildable public contribution summary for one person."""

    __tablename__ = "person_activity_summaries"
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), primary_key=True)
    related_tool_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_tool_count: Mapped[int] = mapped_column(Integer, default=0)
    contribution_count: Mapped[int] = mapped_column(Integer, default=0)
    recent_contribution_count: Mapped[int] = mapped_column(Integer, default=0)
    last_contribution_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity_status: Mapped[str] = mapped_column(String(32), default="unknown")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonReconciliationConflict(Base):
    """An ambiguity intentionally left unresolved by reconciliation."""

    __tablename__ = "person_reconciliation_conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("person_reconciliation_runs.id"), index=True)
    person_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    conflict_type: Mapped[str] = mapped_column(String(64), default="")
    value: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
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


class RepositoryHostMetadata(Base):
    """What a source host publishes about one repository, kept apart from the scan.

    Deliberately not folded into SourceAnalysisReport.report. That payload is
    derived from files this project read itself, under provenance weighting it
    controls; everything here is a third party's assertion, fetched at a
    different time, on a different cadence, and revocable when the host changes
    its mind. Mixing the two would make it impossible to answer "who said this"
    about any single field, and would let a host outage look like a source
    regression.

    Keyed on the repository rather than the tool, because Wikimedia monorepos
    carry several tools at one URL: one row, one fetch, several tools reading
    it. url_hash follows the api_cache convention -- a 2000-character URL
    exceeds MariaDB's index key length, so the digest is the key and the URL is
    stored beside it.

    Every fact column is nullable on purpose. Bitbucket publishes no stars,
    Gerrit no topics, only GitHub and GitLab a license or a contributor count.
    NULL means "this host does not publish this", which is not zero, and code
    that scores it as zero will penalise a tool for its host's API surface.
    """

    __tablename__ = "repository_host_metadata"
    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository_url: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64), default="")
    api: Mapped[str] = mapped_column(String(32), default="")
    # forge or wiki: a wiki-hosted gadget has revisions, not branches.
    kind: Mapped[str] = mapped_column(String(16), default="")
    project_path: Mapped[str] = mapped_column(String(512), default="")

    archived: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    homepage: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # The host's own identifier, upper-cased, not necessarily SPDX.
    license_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    star_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fork_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_issues_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Counts only. The bodies that carry contributor identity are never read,
    # so there is no per-person row here and no email anywhere in this schema.
    contributor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at_upstream: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The host's ETag for the project record. Replaying it makes the next poll
    # conditional, and a 304 costs no GitHub rate budget at all -- which is what
    # keeps a continuous lane under the hourly ceiling.
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
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


class UserScriptPage(Base):
    """One user-space script page on one wiki, as the census last observed it.

    The body is kept, not just its analysis. Re-reading a wiki costs thousands of
    API requests, while re-analysing a stored corpus costs seconds -- and the
    analyzer is the part that keeps changing. Two corrections during the frwiki
    pilot (commented-out imports counted as demand, and `$.getScript` never
    matching) were found and fixed against a stored corpus; without one they
    would each have meant crawling the wiki again.

    `content_model` is what MediaWiki reports, never what the suffix suggests:
    `User:Penquista/monobook.css` is stored here as javascript because that is
    how the wiki parses it.
    """

    __tablename__ = "user_script_pages"
    __table_args__ = (
        UniqueConstraint("wiki", "title"),
        # The directory ranks and collapses per wiki, and the collapse groups by
        # basename before it groups by anything else.
        Index("ix_user_script_pages_wiki_role", "wiki", "role"),
        Index("ix_user_script_pages_wiki_basename", "wiki", "basename"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wiki: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(512))
    owner: Mapped[str] = mapped_column(String(255), default="", index=True)
    basename: Mapped[str] = mapped_column(String(512), default="")
    content_model: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(16), default="")
    fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)
    body: Mapped[str] = mapped_column(MEDIUMTEXT().with_variant(Text, "sqlite"), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[str] = mapped_column(String(32), default="")
    # MediaWiki timestamps, kept as the wiki spells them: they sort correctly as
    # strings, and the directory's "earliest wins" rule only ever compares them.
    created_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    touched_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    # Creation order, not a timestamp. Asking the API when each of 9,345 pages was
    # created is 9,345 requests; the search index hands the same ordering over for
    # free because enumeration already sorts by create_timestamp_asc. The directory
    # only ever compares two pages to see which came first, and this answers that.
    discovery_rank: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # Set when a page the census knew about has gone. Kept rather than deleted:
    # a script that vanished is evidence about the directory, and the people who
    # still import it have a broken load either way.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserScriptImport(Base):
    """One observed load of one page by another, or by a URL.

    Rows are the raw observation and stay that way. Which original a load counts
    towards depends on the collapse, which depends on the loads -- so attribution
    is computed, never stored here.

    A target may be a page on another wiki: 1,160 of frwiki's 1,807 URL imports
    leave the wiki, and those edges are the whole argument for a global gadget.
    A target that resolves to no page at all keeps its URL and an empty title.
    """

    __tablename__ = "user_script_imports"
    __table_args__ = (
        UniqueConstraint("wiki", "source_title", "verb", "target_wiki", "target_title", "target_url"),
        # Demand is always read target-first: "who loads this page?"
        Index("ix_user_script_imports_target", "target_wiki", "target_title"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wiki: Mapped[str] = mapped_column(String(255), index=True)
    source_title: Mapped[str] = mapped_column(String(512), index=True)
    verb: Mapped[str] = mapped_column(String(32), default="")
    target_wiki: Mapped[str] = mapped_column(String(255), default="")
    target_title: Mapped[str] = mapped_column(String(512), default="")
    target_url: Mapped[str] = mapped_column(String(2000), default="")
    is_stylesheet: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserScriptCensusState(Base):
    """Resumable cursor and health for one wiki's script census.

    Enumeration and monitoring are separate cursors on purpose. The full walk is
    a periodic sweep of the search index; `changes_cursor` follows recent changes
    between sweeps and is the only thing that has to be exactly resumable, since
    a missed window is a page the directory never learns changed.

    `enumeration_complete` is false when the wiki holds more pages of a model
    than one search can walk. It is recorded rather than acted on, because a
    truncated enumeration that reads as complete is the failure mode worth
    seeing in the state table.
    """

    __tablename__ = "user_script_census_state"
    wiki: Mapped[str] = mapped_column(String(255), primary_key=True)
    changes_cursor: Mapped[str] = mapped_column(String(32), default="")
    pages_known: Mapped[int] = mapped_column(Integer, default=0)
    scripts_known: Mapped[int] = mapped_column(Integer, default=0)
    imports_known: Mapped[int] = mapped_column(Integer, default=0)
    enumeration_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    enumeration_totals: Mapped[dict] = mapped_column(JSON, default=dict)
    sweeps_completed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserScriptDirectoryEntry(Base):
    """One distinct script in a wiki's directory, as the last projection saw it.

    Derived, and rebuilt whole on every run rather than merged. Which page is the
    original of a script depends on every other page in the corpus and on who
    loads them, so a page appearing or a single import disappearing can move an
    entry that was never itself edited. There is no incremental version of that
    question, and a half-updated directory would rank scripts against demand
    measured at two different times.

    `demand` counts distinct *people*, not distinct source pages: somebody who
    loads a script from both `common.js` and `vector.js` is one user of it, and
    counting the pages would report them as two.
    """

    __tablename__ = "user_script_directory"
    __table_args__ = (
        UniqueConstraint("wiki", "title"),
        # The directory is read one tier at a time, already ordered.
        Index("ix_user_script_directory_position", "wiki", "tier", "position"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wiki: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(512))
    owner: Mapped[str] = mapped_column(String(255), default="", index=True)
    basename: Mapped[str] = mapped_column(String(512), default="")
    tier: Mapped[str] = mapped_column(String(16), default="")
    demand: Mapped[int] = mapped_column(Integer, default=0)
    instances: Mapped[int] = mapped_column(Integer, default=0)
    # Rank within the tier, from 1. Stored because the ordering is what the
    # directory is for, and recomputing it costs a sort over the whole wiki.
    position: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserScriptDirectoryMember(Base):
    """One page filed under a directory entry, and how it got there.

    Kept separate from `UserScriptPage` on purpose. That table records what the
    wiki showed us; this one records what the collapse concluded, and the two
    change for different reasons at different times. Without these rows an entry
    would carry a count of instances and no way to see them -- which is the
    question a security review asks first: not "how many forks", but "which".
    """

    __tablename__ = "user_script_directory_members"
    __table_args__ = (
        UniqueConstraint("wiki", "title"),
        Index("ix_user_script_directory_members_origin", "wiki", "origin_title"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wiki: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(512))
    origin_title: Mapped[str] = mapped_column(String(512))
    # `original`, `copy` (byte-identical), or `variant` (a crowded filename).
    # A copy and a variant are folded by different evidence and a reviewer needs
    # to know which: byte-identical is a fact, a shared name is an inference.
    relation: Mapped[str] = mapped_column(String(16), default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
