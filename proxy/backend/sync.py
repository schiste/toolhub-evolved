# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared provenance and sync-state vocabulary for Evolved-owned records."""

from typing import Any

SOURCE_OFFICIAL = "official"
SOURCE_LOCAL = "local"
SOURCE_REPOSITORY_SCAN = "repository_scan"

SYNC_OFFICIAL = "official"
SYNC_LOCAL_DRAFT = "local_draft"
SYNC_LOCAL_FALLBACK = "local_fallback"
SYNC_EVOLVED_REAL = "evolved_real"
SYNC_ERROR = "sync_error"

REVIEW_OPEN = "open"
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"

AUTHOR_CLAIM_VERIFIED = "verified"
AUTHOR_CLAIM_UNVERIFIED = "unverified"
AUTHOR_CLAIM_STALE = "stale"
AUTHOR_CLAIM_FAILED = "failed"
AUTHOR_CLAIM_REVOKED = "revoked"

AUTHOR_CLAIM_TOOLFORGE_MAINTAINER = "toolforge_maintainer"
AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS = "toolhub_write_access"
AUTHOR_CLAIM_SIGNED_TOOLINFO = "signed_toolinfo"
AUTHOR_CLAIM_TOOLINFO_URL_CONTROL = "toolinfo_url_control"
AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME = "author_display_name"

# A person is an identity record; these are typed relationships from a tool
# to that person. Keep record ownership distinct from operating a tool.
PERSON_REL_AUTHOR = "author"
PERSON_REL_MAINTAINER = "maintainer"
PERSON_REL_RECORD_OWNER = "record_owner"
PERSON_REL_CATALOG_ACTOR = "catalog_actor"
PERSON_REL_VALUES = {
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
    PERSON_REL_RECORD_OWNER,
    PERSON_REL_CATALOG_ACTOR,
}

SOURCE_VALUES = {SOURCE_OFFICIAL, SOURCE_LOCAL, SOURCE_REPOSITORY_SCAN}
SYNC_VALUES = {SYNC_OFFICIAL, SYNC_LOCAL_DRAFT, SYNC_LOCAL_FALLBACK, SYNC_EVOLVED_REAL, SYNC_ERROR}
REVIEW_VALUES = {REVIEW_OPEN, REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED}
AUTHOR_CLAIM_STATUS_VALUES = {
    AUTHOR_CLAIM_VERIFIED,
    AUTHOR_CLAIM_UNVERIFIED,
    AUTHOR_CLAIM_STALE,
    AUTHOR_CLAIM_FAILED,
    AUTHOR_CLAIM_REVOKED,
}
AUTHOR_CLAIM_METHOD_VALUES = {
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
}


def clean_source(value: Any, default: str = SOURCE_LOCAL) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known source value."""
    return value if isinstance(value, str) and value in SOURCE_VALUES else default


def clean_sync_status(value: Any, default: str = SYNC_LOCAL_DRAFT) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known sync-state value."""
    return value if isinstance(value, str) and value in SYNC_VALUES else default


def clean_review_status(value: Any, default: str = REVIEW_PENDING) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known local review-state value."""
    return value if isinstance(value, str) and value in REVIEW_VALUES else default


def clean_author_claim_status(value: Any, default: str = AUTHOR_CLAIM_UNVERIFIED) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known author-claim verification state."""
    return value if isinstance(value, str) and value in AUTHOR_CLAIM_STATUS_VALUES else default


def clean_author_claim_method(value: Any, default: str = AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known author-claim verification method."""
    return value if isinstance(value, str) and value in AUTHOR_CLAIM_METHOD_VALUES else default


def clean_error(value: Any) -> str | None:  # noqa: ANN401 - untrusted JSON
    """Normalize a user-visible sync error string."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:2000] if value else None


def clean_int(value: Any) -> int | None:  # noqa: ANN401 - untrusted JSON
    """Normalize optional official ids coming back from Toolhub."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def created_by_user_id(row: object) -> int | None:
    """Return the local creator id for rows that use either old or new ownership names."""
    for attr in ("created_by_user_id", "user_id"):
        value = getattr(row, attr, None)
        if isinstance(value, int):
            return value
    return None
