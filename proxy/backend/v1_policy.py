# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration and validation policy shared by the versioned API routes.

The route aggregator used to be the accidental owner of these values. Keeping
them here gives each resource blueprint a stable dependency while preserving
the old ``backend.v1`` names as compatibility re-exports.
"""

from backend.models import (
    CatalogCuration,
    ToolHealthTarget,
    ToolMedia,
    ToolRecord,
    ToolThanks,
)
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    REVIEW_APPROVED,
    REVIEW_OPEN,
    REVIEW_PENDING,
    REVIEW_REJECTED,
)

HTTP_NO_CONTENT = 204
HTTP_TOO_MANY = 429
MAX_ITEMS = 500  # per overlay key per user
FEED_KEEP_CAP = 500
RSS_FEED_PAGE_SIZE = 30
RSS_CONTENT_TYPE = "application/rss+xml; charset=utf-8"
DEFAULT_PUBLIC_BASE_URL = "https://toolhub-evolved.toolforge.org"
ME_TOOLS_SEARCH_PAGE_SIZE = 100
ME_TOOLS_MAX_SEARCH_TERMS = 20
SIGNATURE_PLACEHOLDER = "<base64 signature>"
EVENT_TYPES = {"view", "launch", "save", "list_add"}
CLAIM_METHODS = {
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
}
MODERATION_MODELS = {
    "catalog-curations": CatalogCuration,
    "tool-records": ToolRecord,
    "health-targets": ToolHealthTarget,
    "media": ToolMedia,
    "thanks": ToolThanks,
}
PUBLIC_REVIEW_STATUSES = {REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED}
MODERATION_KINDS = set(MODERATION_MODELS)
TOOL_FALLBACK_KINDS = {"new", "edit", "annotations"}
TOOL_OVERLAY_KIND_BY_FALLBACK = {"edit": "edits", "annotations": "annos"}
OFFICIAL_STATUS_DISCARDED = "discarded"
TOOLINFO_CREATE_MAX_ITEMS = 200
TOOLINFO_CREATE_OPT_FIELDS = ("repository", "license", "toolType")
TOOLINFO_CREATE_LIST_FIELDS = ("keywords", "forWikis", "uiLanguages")
TOOLINFO_CREATE_BOOL_FIELDS = ("deprecated", "experimental")
SOURCE_ANALYSIS_REVIEW_STATUSES = {REVIEW_OPEN, REVIEW_APPROVED, REVIEW_REJECTED}
SOURCE_ANALYSIS_DEFAULT_LIMIT = 20
SOURCE_ANALYSIS_MAX_LIMIT = 50
SOURCE_ANALYSIS_NOT_FOUND = "source analysis report not found"
TOOL_SUMMARY_DEFAULT_LIMIT = 24
