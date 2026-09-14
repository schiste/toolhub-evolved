# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource-specific local persistence for the official-first write flow."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from backend import v1_common as common
from backend.models import CrawlerUrl, Favorite, ToolList, ToolOverlay, ToolRecord, User, utcnow
from backend.sync import (
    REVIEW_OPEN,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SOURCE_OFFICIAL,
    SYNC_LOCAL_FALLBACK,
    SYNC_OFFICIAL,
    clean_error,
    clean_review_status,
)


def _sync_metadata(
    row: Any,  # noqa: ANN401 - the supported models share these lifecycle columns
    *,
    sync_status: str,
    failure: dict | None,
    toolhub_body: object | None,
) -> None:
    """Apply the common source, status, error, and response lifecycle fields."""
    row.source = SOURCE_OFFICIAL if sync_status == SYNC_OFFICIAL else SOURCE_LOCAL
    row.sync_status = sync_status
    row.last_synced_at = utcnow() if sync_status == SYNC_OFFICIAL else None
    row.last_error = clean_error(failure["lastError"]) if failure else None
    row.last_toolhub_response = (
        failure["details"] if failure else toolhub_body if isinstance(toolhub_body, dict) else None
    )
    row.validation_errors = failure["validationErrors"] if failure else None


def store_tool_record_fallback(s: Any, user: User, name: str, fields: dict, failure: dict) -> dict:  # noqa: ANN401
    """Create or update one local net-new tool fallback."""
    row = s.execute(
        select(ToolRecord).where(ToolRecord.tool_name == name, ToolRecord.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        row = ToolRecord(tool_name=name, user_id=user.id, created_by_user_id=user.id)
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.record = fields
    row.modified_at = utcnow()
    row.visibility = common.VISIBILITY_PRIVATE
    _sync_metadata(row, sync_status=SYNC_LOCAL_FALLBACK, failure=failure, toolhub_body=None)
    row.review_status = clean_review_status(row.review_status, REVIEW_PENDING)
    row.deleted_at = None
    return common.tool_record_payload(row)


def store_tool_overlay_fallback(  # noqa: PLR0913, PLR0917 - the adapter keeps persistence inputs explicit
    s: Any,  # noqa: ANN401 - SQLAlchemy Session
    user: User,
    name: str,
    kind: str,
    patch: dict,
    failure: dict,
) -> dict:
    """Create or update one local edit/annotation fallback."""
    row = s.execute(
        select(ToolOverlay).where(
            ToolOverlay.kind == kind,
            ToolOverlay.tool_name == name,
            ToolOverlay.user_id == user.id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ToolOverlay(kind=kind, tool_name=name, user_id=user.id, created_by_user_id=user.id)
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.patch = common.data_patch(patch)
    row.modified_at = utcnow()
    _sync_metadata(row, sync_status=SYNC_LOCAL_FALLBACK, failure=failure, toolhub_body=None)
    row.review_status = clean_review_status(row.review_status, REVIEW_OPEN)
    row.deleted_at = None
    return common.with_common_meta(row.patch, row)


def store_list_row(  # noqa: PLR0913 - lifecycle metadata is explicit at this boundary
    s: Any,  # noqa: ANN401 - SQLAlchemy Session
    user: User,
    fields: dict,
    *,
    sync_status: str,
    official_id: int | None = None,
    failure: dict | None = None,
    toolhub_body: object | None = None,
) -> ToolList:
    """Persist the common official/local lifecycle for one list row."""
    row = s.get(ToolList, fields["client_id"])
    if row is None:
        row = ToolList(
            client_id=fields["client_id"],
            user_id=user.id,
            created_by_user_id=user.id,
            title=fields["title"],
        )
        s.add(row)
    row.user_id = user.id
    row.created_by_user_id = row.created_by_user_id or user.id
    row.title = fields["title"]
    row.description = fields["description"]
    row.tools = fields["tools"]
    row.modified_at = utcnow()
    row.official_list_id = official_id
    _sync_metadata(row, sync_status=sync_status, failure=failure, toolhub_body=toolhub_body)
    row.deleted_at = None
    return row


def store_crawler_url_row(  # noqa: PLR0913 - lifecycle metadata is explicit at this boundary
    s: Any,  # noqa: ANN401 - SQLAlchemy Session
    user: User,
    url: str,
    *,
    sync_status: str,
    official_id: int | None = None,
    failure: dict | None = None,
    toolhub_body: object | None = None,
) -> CrawlerUrl:
    """Persist the common official/local lifecycle for one crawler URL."""
    row = s.execute(select(CrawlerUrl).where(CrawlerUrl.user_id == user.id, CrawlerUrl.url == url)).scalar_one_or_none()
    if row is None:
        row = CrawlerUrl(user_id=user.id, created_by_user_id=user.id, url=url[: common.MAX_URL])
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.url = url[: common.MAX_URL]
    row.official_crawler_url_id = official_id
    row.enabled = True
    _sync_metadata(row, sync_status=sync_status, failure=failure, toolhub_body=toolhub_body)
    return row


def upsert_favorite(
    s: Any,  # noqa: ANN401 - SQLAlchemy Session
    user: User,
    name: str,
    *,
    sync_status: str,
    failure: dict | None = None,
) -> Favorite:
    """Create or update a favorite while sharing sync metadata semantics."""
    row = s.execute(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name)
    ).scalar_one_or_none()
    if row is None:
        position = int(
            s.execute(select(func.count()).select_from(Favorite).where(Favorite.user_id == user.id)).scalar_one()
        )
        row = Favorite(user_id=user.id, created_by_user_id=user.id, tool_name=name, position=position)
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.source = SOURCE_OFFICIAL if sync_status == SYNC_OFFICIAL else SOURCE_LOCAL
    row.sync_status = sync_status
    row.last_synced_at = utcnow() if sync_status == SYNC_OFFICIAL else None
    row.last_error = clean_error(failure["lastError"]) if failure else None
    return row
