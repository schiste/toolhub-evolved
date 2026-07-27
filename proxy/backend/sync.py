# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared provenance and sync-state vocabulary for Evolved-owned records."""

from typing import Any

SOURCE_OFFICIAL = "official"
SOURCE_LOCAL = "local"

SYNC_OFFICIAL = "official"
SYNC_LOCAL_DRAFT = "local_draft"
SYNC_LOCAL_FALLBACK = "local_fallback"
SYNC_EVOLVED_REAL = "evolved_real"
SYNC_ERROR = "sync_error"

REVIEW_OPEN = "open"
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"

SOURCE_VALUES = {SOURCE_OFFICIAL, SOURCE_LOCAL}
SYNC_VALUES = {SYNC_OFFICIAL, SYNC_LOCAL_DRAFT, SYNC_LOCAL_FALLBACK, SYNC_EVOLVED_REAL, SYNC_ERROR}
REVIEW_VALUES = {REVIEW_OPEN, REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED}


def clean_source(value: Any, default: str = SOURCE_LOCAL) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known source value."""
    return value if isinstance(value, str) and value in SOURCE_VALUES else default


def clean_sync_status(value: Any, default: str = SYNC_LOCAL_DRAFT) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known sync-state value."""
    return value if isinstance(value, str) and value in SYNC_VALUES else default


def clean_review_status(value: Any, default: str = REVIEW_PENDING) -> str:  # noqa: ANN401 - untrusted JSON
    """Return a known local review-state value."""
    return value if isinstance(value, str) and value in REVIEW_VALUES else default


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
