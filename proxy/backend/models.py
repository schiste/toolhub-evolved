# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLAlchemy models for Evolved-owned data and bounded public caches.

Most rows are complementary records: user accounts, local deltas, verification
claims, and activity. `CanonicalToolCache` is the deliberate exception: it is a
structured public cache of official Toolhub tool records, used for fast fallback
reads while live Toolhub data is stale or unavailable.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar
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
    LIFECYCLE_UNKNOWN,
    LIFECYCLE_VALUES,
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
# Anything that can exceed TEXT's 65,535-*byte* ceiling on MariaDB. SQLite has
# no such ceiling and ignores the declared width, so an oversized value is not
# something any test against the test database can fail on -- it surfaces only
# in production, as a write that raises 1406 mid-request. Declaring the type is
# the only place that ceiling can be respected; `migrate._widen_text_columns`
# carries an existing column across.
LARGE_TEXT = Text().with_variant(MEDIUMTEXT(), "mysql").with_variant(MEDIUMTEXT(), "mariadb")

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
    # Not toolinfo. Evolved's own observation about whether anybody uses a tool,
    # carried in the record under an underscore the way the schema's own
    # non-content keys are, so that one card, one search hit and one tool page
    # all learn it from the field they already read.
    "_lifecycle",
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
    rendered_html: Mapped[str] = mapped_column(LARGE_TEXT, default="")
    rendered_wikitext: Mapped[str] = mapped_column(LARGE_TEXT, default="")
    rendered_text: Mapped[str] = mapped_column(LARGE_TEXT, default="")
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
    """Keyed persistent state: cursors, attestations, and precomputed snapshots.

    Named for the anonymous Toolhub API cache it was built for, and since grown
    into the general place a module parks one value it wants to survive a
    restart. A snapshot lives here rather than in a table of its own because
    what it holds is one opaque document under one key, which is exactly this
    table.
    """

    __tablename__ = "api_cache_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # "Small" was true of the cursors and etags this started with and stopped
    # being true when precomputed snapshots moved in: the user-script roster is
    # ~300 KiB across 1028 wikis, which TEXT rejects outright.
    value: Mapped[str] = mapped_column(LARGE_TEXT)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CanonicalToolCache(Base):
    """Every tool the catalog can show, whatever established that it exists.

    Mostly the official Toolhub catalog. Also records synthesized from what a
    wiki publishes about itself, because a card, a facet, a search hit and an
    author edge are all reached by looking a name up here -- a tool absent
    from this table does not exist as far as the product is concerned.

    `source` says which, and it decides what a catalog snapshot is allowed to
    delete. It defaults to official because for most of this table's life
    that was the only possibility; a writer that leaves the default in place
    is telling the next snapshot it may prune the row.
    """

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
    # Whether anybody other than the author is known to use this tool -- see
    # `backend.sync`. Denormalized out of `record["_lifecycle"]` by the validator
    # below, exactly as search_text and card_record are, so that SQL can filter
    # and facet on it without shipping every record to Python. The record stays
    # the single account of it; a column written independently would be a second
    # one, and the two would eventually disagree.
    #
    # Deliberately left without an index. `_upgrade_schema` adds columns but
    # never indexes, so declaring one here would build it in the test database
    # and nowhere else -- a difference that hides a slow query until production.
    # Nothing filters on this alone yet; when something does, the index is its
    # own deliberate DDL step.
    lifecycle: Mapped[str] = mapped_column(String(16), default="")
    # The two toolinfo status flags, denormalized for the same reason lifecycle
    # is: the Status facet has to filter and count on them in SQL, and reading
    # them out of `record` would mean loading every row into Python to find out
    # how many match. Nullable, and NULL means "not derived yet" -- that is the
    # cursor `backfill_status_flags` walks, and the reason these are not
    # `NOT NULL DEFAULT 0` like `generation`: a false-by-default column is
    # indistinguishable from a tool that really is not deprecated, so a partial
    # backfill would look finished and quietly count too few.
    deprecated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    experimental: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
        lifecycle = source.get("_lifecycle")
        self.lifecycle = lifecycle if lifecycle in LIFECYCLE_VALUES else LIFECYCLE_UNKNOWN
        # `bool()` rather than the raw value: toolinfo carries these as JSON
        # booleans, but a record assembled from a wiki scan or an older
        # generation can hold null or a string, and a non-boolean reaching a
        # BOOLEAN column is a dialect-dependent write rather than an error.
        self.deprecated = bool(source.get("deprecated"))
        self.experimental = bool(source.get("experimental"))
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
    # Several workers invalidate a tool's summary independently, so a DELETE
    # that matches no row means another of them got there first -- the intended
    # end state, reached by someone else. SQLAlchemy warns on that by default
    # because for an entity table it usually signals a lost update; for a cache
    # keyed only by tool name there is nothing to lose, and the warning was
    # arriving in production stderr as though it were a fault.
    __mapper_args__: ClassVar[dict[str, Any]] = {"confirm_deleted_rows": False}
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
    # The summary the job itself printed: how much work it did, and how much of
    # the corpus it has now covered. Nullable because the guard, not the job, is
    # what writes this row -- a child killed before it printed anything still
    # produced a run worth recording, and every row written before jobs handed
    # their summary over has none. NULL means "this run did not say", which is
    # not the same as a run that said it did nothing.
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)


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
    #: True when the scan found a coding assistant's own traces -- a marker
    #: file it defines, or a commit it signed. NULL when it found none, which
    #: is not the same claim as False: an assistant used from an editor, with
    #: nothing about it committed, leaves nothing for a deterministic layer to
    #: find. `status` already separates "scanned and found nothing" from "never
    #: scanned", so nothing is lost by never writing False here -- and a lot
    #: would be lost by writing it, because a reader would take it for proof
    #: that a person wrote every line. backend.source_authorship holds the
    #: evidence rules; the signals behind a True are in the stored report.
    llm_assisted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: The vendor of the assistant, when the evidence names one and does not
    #: contradict itself. Empty for a bare `AGENTS.md`, which names no vendor
    #: at all, and empty when markers name two -- the report's signal list can
    #: say "both", where one column cannot.
    llm_provider: Mapped[str] = mapped_column(String(32), default="")
    #: The model, which in practice only Claude Code's `Co-Authored-By` trailer
    #: ever states outright. Empty everywhere else rather than inferred from
    #: the assistant, because an assistant is not a model and runs as several.
    llm_model: Mapped[str] = mapped_column(String(128), default="")
    #: When this layer last looked. The only way to tell "looked and found
    #: nothing" -- llm_assisted NULL, this set -- from "never looked", which is
    #: both NULL, and the difference the backfill selects on. Without it the
    #: two are indistinguishable and a backfill either re-clones the whole
    #: catalog every run or never terminates.
    llm_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
    that scores it as zero will penalize a tool for its host's API surface.
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
        # Every count of this table is per wiki and excludes deleted pages, and
        # `deleted_at` in no index meant MariaDB read 478,189 whole rows out of
        # a 1.8 GB table to evaluate it -- 25 seconds, to exclude the ten rows
        # that are actually deleted. Carrying the column in the index makes the
        # same count a covering scan. It supersedes the bare `wiki` index this
        # column declares, which migrate.py retires once this one exists.
        Index("ix_user_script_pages_wiki_deleted", "wiki", "deleted_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # No `index=True`: the composite above leads with this column and answers
    # everything a bare index on it would, so declaring both would have a new
    # database create an index the migration exists to retire.
    wiki: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    owner: Mapped[str] = mapped_column(String(255), default="", index=True)
    basename: Mapped[str] = mapped_column(String(512), default="")
    content_model: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(16), default="")
    fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)
    # A sample of the body's shape rather than a hash of it, so two pages that
    # are nearly the same script can be recognized as such. Deliberately not
    # indexed: nothing looks a sketch up, and no two are expected to be equal.
    sketch: Mapped[str] = mapped_column(String(1024), default="")
    body: Mapped[str] = mapped_column(MEDIUMTEXT().with_variant(Text, "sqlite"), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[str] = mapped_column(String(32), default="")
    # MediaWiki timestamps, kept as the wiki spells them: they sort correctly as
    # strings, and the directory's "earliest wins" rule only ever compares them.
    created_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    touched_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    # Whoever signed the page's first revision, as the wiki spells their name.
    # Read from the same replica row that dates the page, because the two are
    # the same fact about the same edit.
    #
    # Usually, but not always, `owner` above. MediaWiki's title rules put
    # `User:Lupin/popups.js` in Lupin's space and nowhere else, which is why
    # `owner` is safe to derive from a title; they say nothing about who typed
    # the first version into it. Measured on fr.wikipedia, 13,479 of 14,433
    # script pages were first written by their owner and 954 by somebody else
    # -- an administrator installing a script for a user, most often. Both
    # facts are kept because they answer different questions: whose space this
    # lives in, and who wrote it.
    #
    # Empty where no replica has answered for this page yet, or where MediaWiki
    # has suppressed the author of that revision.
    first_author_wiki: Mapped[str] = mapped_column(String(255), default="")
    # Creation order, not a timestamp: the order the census enumerated this page
    # in, which is creation order because the search sorts by create_timestamp_asc.
    # It is what the directory falls back to where `created_at_wiki` is empty, and
    # is free where a real date costs a request per page or a replica connection.
    discovery_rank: Mapped[int] = mapped_column(Integer, default=0)
    # The page beside this one, where by wiki convention its author documents
    # it -- `User:Lupin/popups` for `User:Lupin/popups.js`, resolved through any
    # redirect. Empty means the wiki was asked and had no such page, which is
    # indistinguishable here from never having been asked; `docs_checked_at` is
    # what tells those apart, and what keeps every run from asking again.
    docs_title: Mapped[str] = mapped_column(String(512), default="")
    docs_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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

    `target_page_id` is the same edge said in identities rather than in names.
    The names stay: they are what the code on the page actually wrote, and a
    load naming a page nobody has written is still a fact worth keeping. The id
    is only ever set when a page we hold answers to that name, which is why it
    is nullable and stays null for the majority of edges -- a load pointing at
    one of the wikis outside the census can never resolve, and saying so with
    NULL is more honest than inventing a row for it.
    """

    __tablename__ = "user_script_imports"
    __table_args__ = (
        # Named, because widening it in production means dropping the old one
        # by name. `target_module` is part of the key: a page that loads three
        # modules has three edges whose title, wiki, and URL are all blank, and
        # without the module they are one row.
        UniqueConstraint(
            "wiki",
            "source_title",
            "verb",
            "target_wiki",
            "target_title",
            "target_url",
            "target_module",
            name="ux_user_script_imports_edge",
        ),
        # Demand is always read target-first: "who loads this page?"
        Index("ix_user_script_imports_target", "target_wiki", "target_title"),
        # And once resolved, target-first by identity: "who loads *this script*?"
        Index("ix_user_script_imports_target_page", "target_page_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wiki: Mapped[str] = mapped_column(String(255), index=True)
    source_title: Mapped[str] = mapped_column(String(512), index=True)
    verb: Mapped[str] = mapped_column(String(32), default="")
    target_wiki: Mapped[str] = mapped_column(String(255), default="")
    target_title: Mapped[str] = mapped_column(String(512), default="")
    target_url: Mapped[str] = mapped_column(String(2000), default="")
    # A ResourceLoader module name -- `ext.gadget.HotCat` -- for the loads that
    # name one. Separate from `target_title` because a module has no page behind
    # it: stored as a title it is demand for something nobody can ever write,
    # and the resolver would look for it in `user_script_pages` forever.
    target_module: Mapped[str] = mapped_column(String(255), default="")
    # Deliberately a plain integer and not a ForeignKey. The column is added to
    # a live table by additive DDL, which cannot add a constraint alongside it,
    # so declaring one here would exist in a fresh test database and nowhere
    # else -- and a constraint the tests enforce but production does not is
    # worse than no constraint at all. Referential integrity is maintained by
    # the resolver, which only ever writes an id it has just read.
    target_page_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_stylesheet: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserScriptCensusState(Base):
    """Resumable cursor and health for one wiki's script census.

    Enumeration and monitoring are separate cursors on purpose. The full walk is
    a periodic sweep of the search index; `changes_cursor` follows recent changes
    between sweeps and is the only thing that has to be exactly resumable, since
    a missed window is a page the directory never learns changed.

    `enumeration_complete` is false when the enumeration this wiki got was a
    prefix of the truth rather than all of it -- a search index that refused the
    offset, or a sweep that stopped at its budget before the end of the list. It
    is recorded rather than acted on, because a truncated enumeration that reads
    as complete is the failure mode worth seeing in the state table.

    `sweep_cursor` is what makes a wiki too large for one run still converge. It
    indexes an enumeration, so it is only meaningful while the enumeration is
    reproducible -- which the replica's `page_id` order is and a capped search is
    not -- and the sweep drops it rather than trusting it otherwise.
    """

    __tablename__ = "user_script_census_state"
    wiki: Mapped[str] = mapped_column(String(255), primary_key=True)
    changes_cursor: Mapped[str] = mapped_column(String(32), default="")
    pages_known: Mapped[int] = mapped_column(Integer, default=0)
    scripts_known: Mapped[int] = mapped_column(Integer, default=0)
    imports_known: Mapped[int] = mapped_column(Integer, default=0)
    enumeration_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    enumeration_totals: Mapped[dict] = mapped_column(JSON, default=dict)
    # Which road in `backend.userscript_enumeration` named the pages behind this
    # census. The roads are not equivalent and a census keeps whichever one it
    # got, so this is the only thing that can say a finished sweep is finished
    # against a list that is no longer the best available. Empty on a row
    # written before the column existed, which reads as unknown, not as exact.
    enumeration_source: Mapped[str] = mapped_column(String(32), default="")
    sweeps_completed: Mapped[int] = mapped_column(Integer, default=0)
    # How far into the enumeration the last bounded sweep got, and 0 when a
    # sweep finished. A wiki whose corpus is larger than one run's budget is
    # covered by successive runs rather than by the same first slice forever,
    # and only the run that reaches the end counts as a completed sweep.
    sweep_cursor: Mapped[int] = mapped_column(Integer, default=0)
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
        # And across every wiki at once, where `position` -- a rank within one
        # wiki -- means nothing and the order has to come from `demand` itself.
        # `id` is in the index so the whole ORDER BY is served by a backward
        # scan of it: without a tiebreak column MariaDB has to sort every row in
        # the tier -- 36k in the archive today -- to answer for 25. `id` and not
        # (wiki, title), which is the tiebreak this first shipped with: under
        # utf8mb4 those two are 3068 bytes on their own and the index came to
        # 3136, over MariaDB's 3072-byte key limit. SQLite has no such limit, so
        # the tests passed and `migrate` failed in production.
        Index("ix_user_script_directory_demand", "tier", "demand", "id"),
        # And one script at a time, by the identity that outlives the rebuild.
        Index("ix_user_script_directory_script", "script_id"),
    )
    # `id` is this row's identity and lasts until the next projection deletes it.
    # `script_id` is the *script's* identity -- the page the collapse named as
    # the original -- and is the only number here worth writing down anywhere
    # else, because it survives a rebuild that renumbers every row in the table.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # The original page's own first revision, copied from `UserScriptPage` at
    # projection time so the catalogue record can publish a creation date
    # without joining back. A MediaWiki timestamp, or empty where the replica
    # has never answered for that page.
    created_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    # The original page's last edit, copied from `UserScriptPage` at projection
    # time for the same reason as the line above. The original's own date, not
    # the newest across the pages folded onto it: an entry stands for one
    # script, and a near-copy somebody edited last night says nothing about
    # whether the script itself moved.
    touched_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    # The original page's first-revision author, copied from `UserScriptPage`
    # at projection time alongside its dates and for the same reason: the
    # toolinfo record is built from this row alone. The original's own author,
    # not that of any near-copy folded onto it -- whoever forked a script did
    # not write it.
    first_author_wiki: Mapped[str] = mapped_column(String(255), default="")
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
        Index("ix_user_script_directory_members_origin_id", "origin_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The same two edges as the titles below, said in identities. Both are
    # nullable and neither is a ForeignKey, for the reason `UserScriptImport`
    # gives: these columns reach a live table by additive DDL, which cannot
    # carry a constraint, and a constraint that exists only in the test database
    # is worse than none.
    script_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wiki: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(512))
    origin_title: Mapped[str] = mapped_column(String(512))
    # `original`, `copy` (byte-identical), `fork` (most of the same body), or
    # `variant` (a crowded filename). Each is folded by different evidence and a
    # reviewer needs to know which: byte-identical is a fact, a resemblance is an
    # observation, a shared name is an inference.
    relation: Mapped[str] = mapped_column(String(16), default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WikiGadget(Base):
    """One gadget a wiki declares, as its definition page last read it.

    The inventory is kept apart from the catalogue records built out of it. A
    gadget is a fact about a wiki -- it exists, it is hidden, it needs
    `rollback` -- and stays true whether or not anything decided to catalogue
    it. Storing the transcription separately means the elevation rules can
    change, or be re-run against a different judgement about what counts as a
    tool, without re-reading 170 gadgets off two wikis.

    `name_key` exists because production MySQL compares under a collation that
    is case-insensitive and ignores invisible formatting marks, while Python
    compares bytes. A unique index on the raw name would accept two spellings
    Python thinks are different and the database thinks are the same, which is
    precisely how the first Meta census died. Uniqueness is therefore declared
    on a key this code computes, so both sides agree on sameness by
    construction rather than by luck.
    """

    __tablename__ = "wiki_gadgets"
    __table_args__ = (
        UniqueConstraint("wiki", "name_key"),
        Index("ix_wiki_gadgets_wiki_hidden", "wiki", "hidden"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wiki: Mapped[str] = mapped_column(String(255), index=True)
    # As the wiki spells it, which is what a reader sees in Special:Gadgets.
    name: Mapped[str] = mapped_column(String(255))
    # The storage-side spelling of `name`; see the class docstring.
    name_key: Mapped[str] = mapped_column(String(255))
    # The definition page's heading above this line, in the wiki's own language.
    # Recorded, not projected: "Apparence" is a useful grouping on frwiki and
    # noise in a catalogue facet shared with every other wiki.
    section: Mapped[str] = mapped_column(String(255), default="")
    # File names as declared, without the `MediaWiki:Gadget-` prefix.
    pages: Mapped[list] = mapped_column(JSON, default=list)
    # Every declared option, as {option: [values]}; a bare option maps to [].
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    # Denormalized out of `options` because both decide whether a gadget is a
    # user-facing tool, and that question is asked of the whole table at once.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    default_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # The user rights a reader needs before the gadget is offered to them at
    # all, which is the closest thing a definition gives us to an audience.
    rights: Mapped[list] = mapped_column(JSON, default=list)
    # When the gadget's code first existed on the wiki: the oldest first
    # revision among its declared pages, as a MediaWiki timestamp. Distinct
    # from `first_seen_at` below, which is when *we* first read the definition
    # -- HotCat is from 2007 and this catalogue is not. Empty when no replica
    # connection has answered for this wiki yet, so a deployment without
    # `replica.my.cnf` stays correct and simply publishes no creation date.
    created_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    # When the gadget's code was last changed: the newest current-revision
    # timestamp among its declared pages. The definition page is silent about
    # this -- a gadget rewritten last week and one untouched since 2009 declare
    # themselves identically -- and `last_seen_at` below is when this catalogue
    # last read the wiki, which is a fact about our schedule and not about the
    # gadget. Empty where no replica has answered, and published as
    # `modified_date` only when it is not.
    touched_at_wiki: Mapped[str] = mapped_column(String(32), default="")
    # Whoever signed the first revision of the page that dates this gadget --
    # the same page `created_at_wiki` above was taken from, so the name and the
    # date describe one edit rather than two.
    #
    # A gadget has no owner the way a user script does. `MediaWiki:Gadget-HotCat.js`
    # sits in a namespace only administrators can write and belongs to the wiki,
    # so its title names nobody, and the definition line that declares it names
    # nobody either. The first revision is the only evidence a wiki offers about
    # who wrote a gadget, which is why this column exists on the gadget side at
    # all: before it, gadget records were published with no author whatsoever.
    #
    # Empty where no replica has answered for this wiki, where the code lives on
    # another wiki, or where MediaWiki has suppressed that revision's author.
    first_author_wiki: Mapped[str] = mapped_column(String(255), default="")
    # What the wiki itself says this gadget does, from the interface message
    # `MediaWiki:Gadget-<name>` that MediaWiki renders on Special:Gadgets. It is
    # the only description a gadget has and it is a transcription like every
    # other column here -- a community wrote it for its own users, and this
    # catalogue publishes it rather than asking a model to guess at one.
    #
    # Stored reduced to plain text: the message is wikitext aimed at a
    # preferences screen, so it arrives carrying italics, interface links and
    # `<small>` spans that are noise in a JSON description field.
    #
    # In the wiki's own language, not English -- frwiki describes its gadgets in
    # French -- because that is what the wiki wrote. Empty where the wiki
    # declares a gadget whose message nobody ever created, which was 15% of
    # frwiki's gadgets and 1% of Meta's, and empty is published as no
    # description rather than as an empty one.
    description: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # Set when a definition page no longer declares this gadget. Kept rather
    # than deleted so a catalogue record built from it can be retired
    # deliberately instead of losing the reason it existed.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WikiTitlePrefixes(Base):
    """What a title's leading `X:` means on one wiki: a namespace, or another wiki.

    Both are the same problem wearing two hats. MediaWiki serves the user
    namespace under a localized name and accepts an unbounded number of aliases
    for it, so `Benutzer:X/common.js` and `User:X/common.js` are one page on
    dewiki and two strings everywhere else. It also accepts a prefix naming a
    different wiki entirely, so `en:User:Lupin/popups.js` on frwiki is a page on
    enwiki. The census keys pages and load edges on a wiki and a canonical
    title, so either prefix it cannot read is an edge resolving to nothing.

    They are held together because they are read together -- one `meta=siteinfo`
    request answers both -- and because they interact: MediaWiki resolves a
    namespace before an interwiki, and `wikipedia:` on enwiki is both.

    Stored rather than fetched per use because the census that needs them runs
    in one process and the projection that reads its output runs in another, and
    because these names change about as often as a wiki is renamed. A row that
    could not be read keeps what it already had rather than losing it, since a
    wiki being briefly unreachable is not evidence that it renamed anything.
    """

    __tablename__ = "wiki_title_prefixes"
    wiki: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Every name this wiki answers to for namespace 2, canonical name included.
    # A list rather than a joined string because the spellings are matched
    # whole and one of them can contain anything a title can.
    namespaces: Mapped[list] = mapped_column(JSON, default=list)
    # Interwiki prefix -> the host it names, with prefixes that collide with a
    # namespace already removed. Stored as the resolved host rather than as the
    # URL template MediaWiki serves, because the census addresses a page by wiki
    # and title and never by following the link.
    interwiki: Mapped[dict] = mapped_column(JSON, default=dict)
    # When the prefixes above were last read successfully -- what dates them.
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # When a read was last attempted, whether or not it worked. Separate from
    # `read_at` so that a wiki nobody can reach is not asked again by every
    # pass: on one clock an unreadable wiki is permanently stale, and every
    # resolver built spends a request rediscovering that.
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Why the last attempt ended, so an empty prefix set can tell "this wiki has
    # no aliases and no interwiki map" apart from "this wiki has never been read".
    status: Mapped[str] = mapped_column(String(32), default="")


class ListRevisionChange(Base):
    """Which tools one Toolhub list revision added or removed.

    The recent-changes feed says only "Added tool to list" -- the tool is named
    nowhere in it. The name lives in the revision diff, which is a separate
    upstream request, so it is resolved on a schedule and stored here rather
    than fetched while a page renders.

    A row is written for every revision examined, including one whose diff
    touched no tool and one whose diff could not be read. Absence therefore
    means "not looked at yet" and never "looked at and found nothing", which is
    what lets the job find its remaining work by anti-join instead of
    re-fetching every revision it has already seen.
    """

    __tablename__ = "list_revision_changes"
    __table_args__ = (Index("ix_list_revision_changes_list_fetched", "list_id", "fetched_at"),)
    # Toolhub's own revision id, which the recent feed carries as `id`.
    revision_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    list_id: Mapped[int] = mapped_column(Integer, index=True)
    # Tool names as the diff spells them, in the order the diff applied them.
    added: Mapped[list] = mapped_column(JSON, default=list)
    removed: Mapped[list] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # Why a row carries no names: an unreadable diff and a revision that changed
    # only a title look identical otherwise.
    reason: Mapped[str] = mapped_column(String(64), default="")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WikiProject(Base):
    """Every Wikimedia wiki the census can read, and where to read it.

    `meta_p.wiki` is the roster -- it lists about a thousand wikis and already
    omits the private ones, so what it returns is exactly the readable set and
    no second filter is needed. It is copied here rather than queried per run
    because it changes when a wiki is created, renamed or closed, which is a
    few times a year, while the lanes that need it run every hour: asking the
    replicas the same thousand-row question every tick of every lane buys
    nothing but a connection.

    `section` is why this table exists at all. Every wiki on one replica
    instance answers on the same host, and 869 of them share `s3`, so storing
    the instance alongside the name is the difference between a full pass
    opening eight connections and opening a thousand.

    A wiki that disappears from `meta_p` is marked rather than deleted. It has
    pages in the census and catalogue records built from them, and a wiki being
    absent from one roster read -- a renamed database, a truncated answer -- is
    not evidence that its scripts stopped existing.
    """

    __tablename__ = "wiki_projects"
    __table_args__ = (Index("ix_wiki_projects_section_wiki", "section", "wiki"),)
    # The host, as every other table in this codebase spells a wiki:
    # `fr.wikipedia.org`. The census keys on this, not on the database name.
    wiki: Mapped[str] = mapped_column(String(255), primary_key=True)
    # The replica database, without the `_p` suffix the reader adds.
    dbname: Mapped[str] = mapped_column(String(64), index=True)
    # `s1`..`s8`, already stripped of the `.labsdb` spelling `meta_p` uses.
    # Empty means "read this one by its own alias", which still works.
    section: Mapped[str] = mapped_column(String(16), default="")
    family: Mapped[str] = mapped_column(String(64), default="")
    lang: Mapped[str] = mapped_column(String(32), default="")
    # A closed wiki is readable and its scripts are real; it just never changes
    # again. Worth knowing so the schedule can visit it rarely rather than
    # never -- its corpus still has to be discovered once.
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # When the last roster read still listed this wiki. A row whose timestamp
    # stops moving while other rows advance is a wiki that left the roster.
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WikiLaneState(Base):
    """When one wiki was last covered by one lane, and when it is next owed a turn.

    The census used to run over every configured wiki on every tick, which is a
    schedule only because the list had three entries in it. At a thousand wikis
    a run cannot cover everything, so something has to decide what this run
    covers -- and the honest form of that decision is per wiki and per lane,
    because enwiki's user scripts move hourly and a closed wiki's have not moved
    since 2010.

    `cadence_seconds` is per row rather than per lane because the right interval
    is a property of the wiki, and nobody knows it in advance. It is learned
    instead: a run that found work shortens it, a run that found none lengthens
    it, both within bounds the lane sets. A thousand wikis tune themselves to
    roughly the rate they actually change at, which is the only way to spend a
    fixed budget on the wikis that need it.

    Failures move `next_due_at` without touching the cadence. A wiki that cannot
    be read is not a wiki that changed its edit rate, and folding the two
    together would leave a wiki permanently slow after an afternoon of replica
    trouble.
    """

    __tablename__ = "wiki_lane_state"
    __table_args__ = (Index("ix_wiki_lane_state_lane_due", "lane", "next_due_at"),)
    wiki: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Which pass this row is about: `userscript` or `gadget`. They cover the
    # same wikis at different costs and different rates, so they queue apart.
    lane: Mapped[str] = mapped_column(String(32), primary_key=True)
    # When this wiki is next owed a turn in this lane. The queue is ordered by
    # it, so it is the only column the selection reads.
    next_due_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    cadence_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Counted rather than inferred from the timestamps, because "failed twice"
    # and "failed for two days" are different facts and backoff wants the first.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolInference(Base):
    """What a language model said one tool does, read off that tool's own source.

    This is the only table in the catalogue holding a value nobody asserted.
    Every other source transcribes something -- a Toolhub record, a toolinfo.json,
    a gadget definition, a human's correction -- and can be checked against what
    it transcribed. A row here can only be checked against the source code it was
    read from, which is why `page_id` and `source_fingerprint` are stored beside
    the payload rather than just a timestamp: they say exactly which bytes were
    read, so a re-read is possible and a stale row can be spotted.

    Rows are kept for outcomes that produced nothing, too. `status` distinguishes
    "asked, and the answer failed validation" from "asked, and the model was
    unreachable" from "never asked", and without the first two every sweep would
    re-ask the same unanswerable pages ahead of pages nobody has tried.

    `catalog_projection.FILL_ONLY_SOURCES` is what keeps this table subordinate:
    a payload here reaches the projection only where no other source said
    anything, and can never replace or extend what one did.
    """

    __tablename__ = "tool_inference"
    __table_args__ = (
        # The sweep's whole selection is "pages with no current inference", as a
        # join on these two columns. Without the index that join reads the table.
        Index("ix_tool_inference_page_fingerprint", "page_id", "source_fingerprint"),
    )
    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Only the fields validation accepted, under their toolinfo names, so the
    # projection can treat this payload exactly like any other source's.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # The page this was read from, in the lane that produced it -- today only
    # `user_script_pages`. A second lane would need its own join column here
    # rather than reusing this one, since the ids are not comparable.
    page_id: Mapped[int] = mapped_column(Integer, default=0)
    # The body's fingerprint at the time it was read. A page whose fingerprint
    # still matches is never re-sent: the source has not moved, so neither would
    # the answer, and re-sending 37,791 unchanged scripts is the entire cost.
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    # The model's own words, kept only where `detail` says something was
    # refused. Nullable rather than defaulted to "" for the same reason
    # `wiki_gadgets.description` is: 4,260 rows predate this column, and an
    # empty string here would claim the model replied with nothing, when in
    # fact nobody ever wrote the reply down. NULL is how those rows are found.
    reply: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
