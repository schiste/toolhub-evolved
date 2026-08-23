# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared provenance and sync-state vocabulary for Evolved-owned records."""

from typing import Any

SOURCE_OFFICIAL = "official"
SOURCE_LOCAL = "local"
SOURCE_REPOSITORY_SCAN = "repository_scan"
# A record this codebase synthesized from what a wiki publishes about a
# gadget, rather than one anybody wrote by hand or Toolhub handed us.
SOURCE_WIKI_GADGET = "wiki_gadget"
# The same, for a user-space script page the census read and the directory
# named as an original. Kept apart from SOURCE_WIKI_GADGET because the two are
# established by different evidence -- a gadget is declared by the wiki, a user
# script is inferred from a corpus -- and because a catalog operator has to be
# able to prune or trust one without the other.
SOURCE_WIKI_USERSCRIPT = "wiki_userscript"

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
# Public product relationships are deliberately narrower than the internal
# evidence graph. Record authority and catalog activity remain available to
# authorization, contributor eligibility, reconciliation, and audit code.
PUBLIC_PERSON_REL_VALUES = (PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER)

# Whether anybody other than a tool's own author is known to use it. This is
# Evolved's observation, not the maintainer's claim, and it is deliberately not
# the toolinfo `deprecated` flag: "deprecated" means an author said stop using
# this, while "archived" here means only that nothing this codebase can see
# loads it. Inferring the first from the second would put words in a
# maintainer's mouth. An empty value is the honest default and means nothing has
# measured this tool either way, which is true of everything Toolhub hands us.
LIFECYCLE_UNKNOWN = ""
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_ARCHIVED = "archived"
LIFECYCLE_VALUES = {LIFECYCLE_UNKNOWN, LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED}

SOURCE_VALUES = {SOURCE_OFFICIAL, SOURCE_LOCAL, SOURCE_REPOSITORY_SCAN, SOURCE_WIKI_GADGET, SOURCE_WIKI_USERSCRIPT}
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
