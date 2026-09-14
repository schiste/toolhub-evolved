# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure response serializers shared by the /v1 resource modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.author_claims import claim_payload as author_claim_payload
from backend.author_claims import public_key_fingerprint
from backend.sync import (
    REVIEW_APPROVED,
    REVIEW_OPEN,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SYNC_ERROR,
    SYNC_EVOLVED_REAL,
    SYNC_LOCAL_DRAFT,
    SYNC_LOCAL_FALLBACK,
    SYNC_OFFICIAL,
    clean_review_status,
)
from backend.v1_contracts import VISIBILITY_PRIVATE, VISIBILITY_PUBLIC

if TYPE_CHECKING:
    from datetime import datetime

    from backend.models import (
        CrawlerUrl,
        SourceAnalysisReport,
        ToolAuthorClaim,
        ToolAuthorKey,
        ToolHealthTarget,
        ToolList,
        ToolMedia,
        ToolRecord,
        ToolThanks,
    )


def iso(dt: datetime | None) -> str:
    """Naive-UTC column value → ISO-8601 with the Z suffix the SPA emits."""
    return dt.isoformat(timespec="seconds") + "Z" if dt else ""


def media_payload(row: ToolMedia) -> dict:
    return {
        "id": row.id,
        "toolName": row.tool_name,
        "url": row.url,
        "title": row.title,
        "license": row.license,
        "source": row.source,
        "reviewStatus": clean_review_status(row.review_status, REVIEW_PENDING),
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": sync_label(row.sync_status or SYNC_EVOLVED_REAL),
        "createdAt": iso(row.created_at),
    }


def sync_label(status: str | None) -> str:
    labels = {
        SYNC_OFFICIAL: "Official Toolhub",
        SYNC_LOCAL_DRAFT: "Local draft",
        SYNC_LOCAL_FALLBACK: "Local fallback",
        SYNC_EVOLVED_REAL: "Evolved data",
        SYNC_ERROR: "Sync error",
    }
    return labels.get(status or "", "Local draft")


def with_common_meta(payload: dict, row: object, *, include_official_id: bool = False) -> dict:
    """Attach provenance fields without disturbing legacy payload shapes."""
    out = dict(payload)
    source = getattr(row, "source", None) or SOURCE_LOCAL
    status = getattr(row, "sync_status", None) or SYNC_LOCAL_DRAFT
    out["source"] = source
    out["syncStatus"] = status
    out["syncLabel"] = sync_label(status)
    if getattr(row, "last_synced_at", None):
        out["lastSyncedAt"] = iso(row.last_synced_at)
    if getattr(row, "last_error", None):
        out["lastError"] = row.last_error
    if include_official_id and getattr(row, "official_list_id", None) is not None:
        out["officialId"] = row.official_list_id
    if include_official_id and getattr(row, "official_crawler_url_id", None) is not None:
        out["officialId"] = row.official_crawler_url_id
        out["id"] = row.official_crawler_url_id
    if getattr(row, "last_toolhub_response", None):
        out["toolhubResponse"] = row.last_toolhub_response
    if getattr(row, "validation_errors", None):
        out["validationErrors"] = row.validation_errors
    return out


def list_payload(row: ToolList) -> dict:
    return with_common_meta(
        {
            "id": row.client_id,
            "title": row.title,
            "description": row.description,
            "tools": row.tools,
            "created": iso(row.created_at),
            "modified": iso(row.modified_at),
        },
        row,
        include_official_id=True,
    )


def crawler_url_payload(row: CrawlerUrl) -> dict:
    return with_common_meta(
        {
            "url": row.url,
            "added": iso(row.added_at),
            "localId": row.id,
            "enabled": row.enabled,
            "lastCheckedAt": iso(row.last_checked_at),
            "lastStatus": row.last_status or "",
        },
        row,
        include_official_id=True,
    )


def local_tool_is_public(row: ToolRecord) -> bool:
    """Public Evolved records are searchable/feedable; private drafts are not."""
    record = row.record if isinstance(row.record, dict) else {}
    is_public = row.visibility == VISIBILITY_PUBLIC or record.get("origin") == "crawler"
    return is_public and clean_review_status(getattr(row, "review_status", None), REVIEW_PENDING) == REVIEW_APPROVED


def tool_record_payload(row: ToolRecord) -> dict:
    record = row.record if isinstance(row.record, dict) else {}
    out = with_common_meta(record, row)
    out["visibility"] = row.visibility or VISIBILITY_PRIVATE
    out["reviewStatus"] = clean_review_status(getattr(row, "review_status", None), REVIEW_PENDING)
    if row.official_name:
        out["officialName"] = row.official_name
    if row.last_toolhub_response:
        out["toolhubResponse"] = row.last_toolhub_response
    if row.validation_errors:
        out["validationErrors"] = row.validation_errors
    return out


def health_target_payload(row: ToolHealthTarget) -> dict:
    return {
        "id": row.id,
        "toolName": row.tool_name,
        "targetUrl": row.target_url,
        "enabled": row.enabled,
        "reviewStatus": clean_review_status(row.review_status, REVIEW_PENDING),
        "lastCheckedAt": iso(row.last_checked_at),
        "lastStatus": row.last_status or "",
        "lastError": row.last_error or "",
        "source": SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": sync_label(row.sync_status or SYNC_EVOLVED_REAL),
        "createdAt": iso(row.created_at),
    }


def thanks_payload(row: ToolThanks) -> dict:
    return {
        "id": row.id,
        "toolName": row.tool_name,
        "active": row.active,
        "reviewStatus": clean_review_status(row.review_status, REVIEW_APPROVED),
        "source": SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": sync_label(row.sync_status or SYNC_EVOLVED_REAL),
        "createdAt": iso(row.created_at),
        "updatedAt": iso(row.updated_at),
    }


def moderation_item(kind: str, row: object) -> dict:
    payload_builders = {
        "catalog-curations": lambda item: {
            "id": item.id,
            "toolName": item.tool_name,
            "patch": item.patch,
            "rationale": item.rationale,
            "reviewStatus": item.review_status,
            "createdByUserId": item.created_by_user_id,
            "createdAt": iso(item.created_at),
            "modifiedAt": iso(item.modified_at),
        },
        "tool-records": tool_record_payload,
        "health-targets": health_target_payload,
        "media": media_payload,
        "thanks": thanks_payload,
    }
    return {"kind": kind, "id": row.id, "data": payload_builders[kind](row)}


def claim_payload(row: ToolAuthorClaim) -> dict:
    """Serialize one stored author claim into the resolver response contract."""
    return author_claim_payload(row)


def author_key_payload(row: ToolAuthorKey) -> dict:
    """Serialize one registered public key for account export."""
    return {
        "keyId": row.key_id,
        "algorithm": row.algorithm,
        "fingerprint": public_key_fingerprint(row.public_key),
        "publicKey": row.public_key,
        "createdAt": iso(row.created_at),
        "revokedAt": iso(row.revoked_at),
        "lastUsedAt": iso(row.last_used_at),
    }


def source_analysis_payload(row: SourceAnalysisReport) -> dict:
    """Serialize one source-analysis report without raw submitted source."""
    report = row.report if isinstance(row.report, dict) else {}
    return {
        "id": row.id,
        "toolName": row.tool_name or "",
        "sourceLabel": row.source_label or "",
        "reviewStatus": clean_review_status(row.review_status, REVIEW_OPEN),
        "reviewNotes": row.review_notes or "",
        "createdAt": iso(row.created_at),
        "reviewedAt": iso(row.reviewed_at),
        "source": row.source or SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": sync_label(row.sync_status or SYNC_EVOLVED_REAL),
        "report": report,
    }
