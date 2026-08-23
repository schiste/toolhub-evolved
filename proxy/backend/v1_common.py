# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers shared by every /v1 route module.

backend/v1.py was split by resource family, and the families kept reaching
back into its private helpers — which is what those names are no longer for.
They live here under public names instead, so the shared surface is stated
rather than implied and nothing has to poke at another module's internals.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from flask import Response, abort, jsonify, request, session
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from backend import (
    activity_privacy,
    api_cache,
    authz,
    db,
    maintainer_index,
    people_index,
    toolhub,
)
from backend.author_claims import (
    ToolhubWriteProvider,
    public_key_fingerprint,
    record_author_claim,
)
from backend.author_claims import (
    claim_payload as author_claim_payload,
)
from backend.models import (
    ActivityRow,
    CrawlerUrl,
    Favorite,
    Person,
    PersonProfile,
    SourceAnalysisReport,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolHealthTarget,
    ToolinfoControlChallenge,
    ToolList,
    ToolMedia,
    ToolOverlay,
    ToolPersonRelationship,
    ToolRecord,
    ToolThanks,
    User,
    utcnow,
)
from backend.security import current_user_id
from backend.sync import (
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_VERIFIED,
    REVIEW_APPROVED,
    REVIEW_OPEN,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SYNC_ERROR,
    SYNC_EVOLVED_REAL,
    SYNC_LOCAL_DRAFT,
    SYNC_LOCAL_FALLBACK,
    SYNC_OFFICIAL,
    clean_error,
    clean_int,
    clean_review_status,
)
from backend.toolinfo_control import (
    CHALLENGE_FIELD,
    CHALLENGE_STATUS_EXPIRED,
    CHALLENGE_STATUS_PENDING,
    CHALLENGE_STATUS_VERIFIED,
    CHALLENGE_TTL,
    CONTROL_CLAIM_TTL,
    fetch_matching_item,
    new_token,
)
from backend.toolinfo_control import (
    expired as challenge_expired,
)

HTTP_BAD_REQUEST = 400


HTTP_NOT_FOUND = 404


HTTP_UNAUTHORIZED = 401


HTTP_FORBIDDEN = 403


HTTP_CONFLICT = 409


HTTP_BAD_GATEWAY = 502


UPSTREAM_KIND_INDEX = 1


UPSTREAM_MIN_PARTS = 2


UPSTREAM_OBJECT_INDEX = 2


UPSTREAM_OBJECT_PARTS = 3


MAX_NAME = 255


FEED_READ_CAP = 100


AUTHOR_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


OVERLAY_KINDS = {"toolEdits": "edits", "toolAnnos": "annos"}


FEED_KEYS = ("revisions", "auditlogs")


VISIBILITY_PRIVATE = "private"


VISIBILITY_PUBLIC = "public"


META_KEYS = {
    "source",
    "syncStatus",
    "syncLabel",
    "lastSyncedAt",
    "lastError",
    "createdByUserId",
    "created_by_user_id",
    "deletedAt",
    "deleted_at",
    "officialId",
    "officialName",
    "visibility",
    "toolhubResponse",
    "validationErrors",
    "viewerOwned",
    "baseRevision",
    "fieldStatuses",
    "reviewStatus",
}


CANONICAL_TOOL_KEYS = {"name", "origin"}


TOOLHUB_WRITE_PROVIDER = ToolhubWriteProvider()


TOOL_SUMMARY_MAX_NAMES = 50


HEALTH_GRADE_STRONG = 85


HEALTH_GRADE_GOOD = 70


HEALTH_GRADE_ATTENTION = 50


RUNTIME_HEALTH_SCORES = {"healthy": 95, "ok": 90, "degraded": 55, "down": 15, "error": 20}


PUBLIC_JSON_CACHE_SECONDS = 5 * 60


PUBLIC_JSON_STALE_IF_ERROR_SECONDS = 24 * 60 * 60


def iso(dt: datetime | None) -> str:
    """Naive-UTC column value → ISO-8601 with the Z suffix the SPA emits."""
    return dt.isoformat(timespec="seconds") + "Z" if dt else ""


def parse_iso(value: Any) -> datetime:  # noqa: ANN401 — untrusted JSON in
    """Client ISO timestamp → naive UTC datetime (now() when absent/invalid)."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return utcnow()
    return parsed if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)


def parse_optional_iso(value: Any) -> datetime | None:  # noqa: ANN401 — untrusted JSON in
    """Client ISO timestamp → naive UTC datetime, preserving absence."""
    if value in (None, ""):
        return None
    return parse_iso(value)


def payload_value(payload: dict, camel: str, snake: str | None = None) -> Any:  # noqa: ANN401
    """Read either frontend camelCase or backend snake_case metadata keys."""
    if camel in payload:
        return payload.get(camel)
    return payload.get(snake or camel)


def clean_name(value: str) -> str | None:
    value = str(value or "").strip()
    return value[:MAX_NAME] if value else None


def public_json_response(payload: dict[str, Any], *, max_age: int = PUBLIC_JSON_CACHE_SECONDS) -> Response:
    """Return cacheable JSON with an ETag validator for public local-data endpoints."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    headers = {
        "Cache-Control": f"public, max-age={max_age}, stale-if-error={PUBLIC_JSON_STALE_IF_ERROR_SECONDS}",
        "ETag": etag,
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers=headers)
    return Response(body, headers=headers, content_type="application/json; charset=utf-8")


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


def bad(error: str, validation_errors: list | None = None) -> Response:
    payload: dict[str, Any] = {"error": error}
    if validation_errors:
        payload["lastError"] = error
        payload["validationErrors"] = validation_errors
    resp = jsonify(payload)
    resp.status_code = HTTP_BAD_REQUEST
    return resp


def url_validation_message(value: Any, *, label: str, https_only: bool = True) -> str | None:  # noqa: ANN401
    """Validate URL-shaped write inputs before they reach Toolhub or crawler code."""
    message = None
    if not isinstance(value, str) or not value.strip():
        message = f"{label} is required."
    else:
        url = value.strip()
        try:
            parsed = urlparse(url)
            host = parsed.hostname
        except ValueError:
            parsed = None
            host = None
            message = f"{label} is not a valid URL."
        allowed = ("https",) if https_only else ("http", "https")
        if message is None and len(url) > MAX_URL:
            message = f"{label} must be {MAX_URL} characters or fewer."
        elif message is None and any(char.isspace() for char in url):
            message = f"{label} cannot contain spaces."
        elif message is None and parsed is not None and parsed.scheme.lower() not in allowed:
            message = f"{label} must use {'https' if https_only else 'http or https'}."
        elif message is None and (parsed is None or not parsed.netloc or not host):
            message = f"{label} must include a host."
    return message


def url_validation_bad(field: str, message: str) -> Response:
    return bad(message, [{"field": field, "message": message}])


def deny(status: int, error: str) -> Response:
    resp = jsonify({"error": error})
    resp.status_code = status
    return resp


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


def author_claim_owned_by(user: User):  # noqa: ANN201 - returns a SQLAlchemy boolean expression
    """Match stable account ownership, with a narrow legacy username fallback."""
    return or_(
        ToolAuthorClaim.user_id == user.id,
        and_(ToolAuthorClaim.user_id.is_(None), ToolAuthorClaim.toolhub_username == user.username),
    )


def author_key_owned_by(user: User):  # noqa: ANN201 - returns a SQLAlchemy boolean expression
    """Match stable account ownership, with a narrow legacy username fallback."""
    return or_(
        ToolAuthorKey.user_id == user.id,
        and_(ToolAuthorKey.user_id.is_(None), ToolAuthorKey.toolhub_username == user.username),
    )


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


def score_grade(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= HEALTH_GRADE_STRONG:
        return "strong"
    if score >= HEALTH_GRADE_GOOD:
        return "good"
    if score >= HEALTH_GRADE_ATTENTION:
        return "needs-attention"
    return "high-risk"


def health_status(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= HEALTH_GRADE_STRONG:
        return "healthy"
    if score >= HEALTH_GRADE_ATTENTION:
        return "watch"
    return "at-risk"


def bounded_score(value: int) -> int:
    return max(0, min(100, value))


def summary_dimension(  # noqa: PLR0913, PLR0917 - explicit fields keep scoring dimensions auditable.
    key: str,
    label: str,
    score: int | None,
    weight: float,
    status: str,
    summary: str,
    *,
    confidence: float = 0.5,
    source: str = SOURCE_LOCAL,
) -> dict[str, Any]:
    bounded = bounded_score(score) if score is not None else None
    return {
        "key": key,
        "label": label,
        "score": bounded,
        "grade": score_grade(bounded),
        "weight": weight,
        "status": status or score_grade(bounded),
        "summary": summary,
        "confidence": round(max(0.1, min(0.99, confidence)), 2),
        "source": source,
        "includedInScore": bounded is not None,
    }


def latest_public_health_core_statement(tool_name: str) -> Select[tuple[SourceAnalysisReport]]:
    return (
        select(SourceAnalysisReport)
        .where(
            SourceAnalysisReport.tool_name == tool_name,
            SourceAnalysisReport.review_status == REVIEW_APPROVED,
        )
        .order_by(
            SourceAnalysisReport.reviewed_at.is_(None),
            SourceAnalysisReport.reviewed_at.desc(),
            SourceAnalysisReport.created_at.desc(),
            SourceAnalysisReport.id.desc(),
        )
        .limit(1)
    )


def source_repository_summary(report: dict[str, Any]) -> dict[str, Any] | None:
    context = report.get("repositoryContext") if isinstance(report.get("repositoryContext"), dict) else {}
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    if not repository:
        return None

    summary: dict[str, Any] = {}
    for key in (
        "url",
        "branch",
        "defaultBranch",
        "commitSha",
        "lastCommitAt",
        "analyzedAt",
        "provider",
        "tag",
    ):
        value = repository.get(key)
        if value is not None and str(value).strip():
            summary[key] = str(value).strip()
    for key in ("commitCount", "contributorCount", "lastCommitAgeDays"):
        value = clean_int(repository.get(key))
        if value is not None:
            summary[key] = value
    # False is kept and absent is dropped, the same rule the scanner's
    # _host_facts applies upstream: a host that says "not archived" has told us
    # something, a host with no such field has not. Dropping False here would
    # have made the two indistinguishable in the one place a reader sees them.
    for key in ("archived", "dirty"):
        value = repository.get(key)
        if isinstance(value, bool):
            summary[key] = value
    return summary or None


#: How many versioned technologies the public summary carries. The analyzer
#: caps the patch it suggests at 20, so a longer list here would describe
#: something the catalog never shows.
MAX_PUBLIC_TECHNOLOGIES = 20


def source_technology_summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect the declared version behind each detected technology.

    A technology with no version is left out rather than carried with an empty
    one: the catalog already lists the technology, and this exists only to say
    which release. Two manifests disagreeing produce a row with `spec` and no
    `version` -- there is a declaration to show, but no single answer.
    """
    rows = report.get("technology") if isinstance(report.get("technology"), list) else []
    summary: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        version = str(row.get("version") or "")
        specs = row.get("versionSpecs") if isinstance(row.get("versionSpecs"), list) else []
        spec = str(specs[0]) if len(specs) == 1 else ""
        if not version and not spec:
            continue
        entry: dict[str, Any] = {"value": str(row.get("value") or ""), "label": str(row.get("label") or "")}
        if version:
            entry["version"] = version
        if spec:
            entry["spec"] = spec
        summary.append(entry)
        if len(summary) >= MAX_PUBLIC_TECHNOLOGIES:
            break
    return summary


def latest_public_health_core(s: Any, tool_name: str) -> dict[str, Any] | None:  # noqa: ANN401 - SQLAlchemy session
    row = s.execute(latest_public_health_core_statement(tool_name)).scalars().first()
    report = row.report if row is not None and isinstance(row.report, dict) else {}
    health_core = report.get("healthCore") if isinstance(report.get("healthCore"), dict) else None
    if not health_core:
        return None
    return {
        "score": clean_int(health_core.get("score")),
        "grade": str(health_core.get("grade") or "unknown"),
        "confidence": float(health_core.get("confidence") or 0),
        "sourceMaintenanceStatus": str(health_core.get("sourceMaintenanceStatus") or "unknown"),
        "maintainerActivityStatus": str(health_core.get("maintainerActivityStatus") or "unknown"),
        "stewardshipStatus": str(health_core.get("stewardshipStatus") or "needs-context"),
        "replacedBy": str(health_core.get("replacedBy") or ""),
        "dimensions": health_core.get("dimensions") if isinstance(health_core.get("dimensions"), list) else [],
        "repository": source_repository_summary(report),
        "technologies": source_technology_summary(report),
        "createdAt": iso(row.created_at),
        "reviewedAt": iso(row.reviewed_at),
        "source": SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
    }


def health_target_dimension(health: ToolHealthTarget | None) -> dict[str, Any] | None:
    if health is None:
        return None
    status = str(health.last_status or "unknown")
    score = RUNTIME_HEALTH_SCORES.get(status)
    return summary_dimension(
        "runtime-health",
        "Runtime health",
        score,
        1.0,
        status,
        "Latest approved Evolved health target result.",
        confidence=0.9 if score is not None else 0.35,
        source=SOURCE_LOCAL,
    ) | {
        "checkedAt": iso(health.last_checked_at),
        "targetUrl": health.target_url,
        "lastError": health.last_error or "",
    }


def maintainer_activity_label(activity_status: str, summary_status: str) -> str:
    if activity_status in {"active", "quiet"} and summary_status in {"verified", "probable"}:
        return "maintained"
    if activity_status in {"active", "quiet"}:
        return "active-maintainer"
    if activity_status in {"stale", "dormant"}:
        return "maintainer-stale"
    if summary_status in {"verified", "probable"}:
        return "verified-maintainer"
    return "unknown"


def maintainer_dimension(summary: dict[str, Any]) -> dict[str, Any]:
    counts = summary.get("healthCounts") if isinstance(summary.get("healthCounts"), dict) else {}
    people = summary.get("people") if isinstance(summary.get("people"), list) else []
    best = people[0] if people and isinstance(people[0], dict) else {}
    activity = best.get("activity") if isinstance(best.get("activity"), dict) else {}
    summary_status = str(summary.get("status") or "unknown")
    activity_status = str(activity.get("status") or "unknown")
    score = clean_int(summary.get("bestConfidence"))
    if score is not None:
        if activity_status == "active":
            score += 5
        elif activity_status == "quiet":
            score -= 5
        elif activity_status == "stale":
            score -= 25
        elif activity_status == "dormant":
            score -= 40
        if clean_int(counts.get("verifiedPeople")):
            score += 5
        if not clean_int(counts.get("people")):
            score = None
    label = maintainer_activity_label(activity_status, summary_status)
    return summary_dimension(
        "maintainer-status",
        "Maintainer status",
        bounded_score(score) if score is not None else None,
        1.25,
        label,
        "Derived from Evolved maintainer evidence confidence and local maintainer activity.",
        confidence=0.85 if people else 0.2,
        source=SOURCE_LOCAL,
    ) | {
        "summaryStatus": summary_status,
        "activityStatus": activity_status,
        "bestConfidence": clean_int(summary.get("bestConfidence")) or 0,
        "counts": counts,
    }


def health_summary_from_dimensions(
    tool_name: str,
    dimensions: list[dict[str, Any]],
    *,
    source_health: dict[str, Any] | None,
) -> dict[str, Any]:
    included = [item for item in dimensions if item.get("includedInScore") and item.get("score") is not None]
    weight = sum(float(item.get("weight") or 0) for item in included)
    score = (
        round(sum(float(item["score"]) * float(item.get("weight") or 0) for item in included) / weight)
        if weight
        else None
    )
    return {
        "toolName": tool_name,
        "score": score,
        "grade": score_grade(score),
        "status": health_status(score),
        "confidence": (
            round(weight / sum(float(item.get("weight") or 0) for item in dimensions), 2) if dimensions else 0
        ),
        "dimensions": dimensions,
        "sourceHealth": source_health,
        "calculation": {
            "formula": "weighted_average(included dimension scores)",
            "includedWeight": round(weight, 2),
            "dimensionCount": len(dimensions),
            "includedDimensionCount": len(included),
        },
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
    }


def tool_names_from_request() -> list[str]:
    names = request.args.getlist("name")
    names.extend(str(request.args.get("names") or "").split(","))
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        clean = clean_name(name)
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out[:TOOL_SUMMARY_MAX_NAMES]


def build_local_tool_summary(s: Any, tool_name: str) -> dict[str, Any]:  # noqa: ANN401 - SQLAlchemy session
    maintainer_index.sync_author_claim_edges(s, tool_names=[tool_name])
    person_ids = {
        row[0]
        for row in s.execute(
            select(ToolPersonRelationship.person_id).where(ToolPersonRelationship.tool_name == tool_name).distinct()
        ).all()
    }
    people_index.refresh_activity_summaries(s, person_ids=person_ids)
    maintainer_summary = maintainer_index.public_tool_summary(s, tool_name)
    source_health = latest_public_health_core(s, tool_name)
    dimensions: list[dict[str, Any]] = []
    if source_health:
        dimensions.append(
            summary_dimension(
                "source-health",
                "Source health",
                clean_int(source_health.get("score")),
                1.5,
                str(source_health.get("stewardshipStatus") or source_health.get("grade") or "unknown"),
                "Latest approved deterministic source-analysis health core.",
                confidence=float(source_health.get("confidence") or 0.1),
                source=SOURCE_LOCAL,
            )
        )
    dimensions.append(maintainer_dimension(maintainer_summary))
    health = (
        s.execute(
            select(ToolHealthTarget)
            .where(ToolHealthTarget.tool_name == tool_name, ToolHealthTarget.enabled.is_(True))
            .where(ToolHealthTarget.deleted_at.is_(None), ToolHealthTarget.review_status == REVIEW_APPROVED)
            .order_by(ToolHealthTarget.last_checked_at.desc(), ToolHealthTarget.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    health_dimension = health_target_dimension(health)
    if health_dimension is not None:
        dimensions.append(health_dimension)
    return {
        "toolName": tool_name,
        "health": health_summary_from_dimensions(tool_name, dimensions, source_health=source_health),
        "maintainer": maintainer_summary,
        "maintainerDimension": dimensions[0 if not source_health else 1],
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
    }


def clean_author_key_id(value: Any) -> str | None:  # noqa: ANN401 - untrusted JSON
    """Return a valid author-key id for signed toolinfo metadata."""
    text_value = str(value or "").strip()
    return text_value if AUTHOR_KEY_ID_RE.fullmatch(text_value) else None


def toolhub_tool_detail(tool_name: str) -> dict | None:
    """Fetch one exact official Toolhub tool record by name."""
    payload = toolhub.public_api_get(f"/api/tools/{quote(tool_name, safe='')}/")
    return payload if isinstance(payload, dict) and clean_name(payload.get("name")) else None


def record_successful_toolhub_write(
    user: User,
    method: str,
    path: str,
    request_payload: object | None,
    response_payload: object | None,
) -> None:
    """Persist Toolhub write-access evidence without affecting the completed write."""
    try:
        with db.session_scope() as s:
            TOOLHUB_WRITE_PROVIDER.record_success(
                s,
                user,
                method=method,
                path=path,
                request_payload=request_payload,
                response_payload=response_payload,
            )
            maintainer_index.sync_author_claim_edges(s, user_ids=[user.id])
    except Exception:  # noqa: BLE001 - provider evidence must never break a successful official write.
        return


def current_policy_user() -> tuple[User | None, Response | None]:
    """Fetch the session user for Evolved-local policy checks."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required/write_guard guarantees this
    with db.session_scope() as s:
        user = s.get(User, uid)
    # current_user_id() already refuses a session whose user row is gone, so this
    # only fires if the account is deleted between that check and this one. Kept
    # for that race; unreachable from a test, hence the pragma.
    if user is None:  # pragma: no cover - delete-mid-request race
        session.clear()
        return None, deny(HTTP_UNAUTHORIZED, "sign in required")
    return user, None


def enforce(user: User, action: str, resource: object | None = None) -> Response | None:
    """Return a 403 when the Evolved-local policy rejects the action."""
    return None if authz.can(user, action, resource) else deny(HTTP_FORBIDDEN, "not allowed")


def require_policy(action: str, resource: object | None = None) -> tuple[User | None, Response | None]:
    """Fetch the current user and enforce one Evolved-local policy action."""
    user, denied = current_policy_user()
    if denied is not None:  # pragma: no cover - only the race above denies here
        return None, denied
    assert user is not None  # noqa: S101 — current_policy_user returned no denial
    denied = enforce(user, action, resource)
    if denied is not None:
        return None, denied
    return user, None


def require_policy_or_abort(action: str, resource: object | None = None) -> User:
    """Return the current user or abort with a normalized policy response."""
    user, denied = require_policy(action, resource)
    if denied is not None:
        abort(denied)
    assert user is not None  # noqa: S101 — require_policy returned no denial
    return user


def upstream_path(fragment: str) -> str:
    """Build a fixed official Toolhub API path from a route fragment."""
    return f"/api/{fragment.lstrip('/')}"


def upstream_path_parts(path: str) -> list[str]:
    """Return decoded pieces from an official Toolhub API path."""
    return [unquote(part) for part in path.strip("/").split("/") if part]


def string_payload_value(payload: object | None, *keys: str) -> str | None:
    """Return the first non-empty string-like value from a JSON object payload."""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def invalidate_official_api_cache(path: str, request_payload: object | None, response_payload: object | None) -> None:
    """Invalidate anonymous cached reads affected by a successful official write."""
    parts = upstream_path_parts(path)
    if len(parts) < UPSTREAM_MIN_PARTS or parts[0] != "api":
        return
    if parts[UPSTREAM_KIND_INDEX] == "tools":
        tool_name = (
            parts[UPSTREAM_OBJECT_INDEX]
            if len(parts) >= UPSTREAM_OBJECT_PARTS
            else string_payload_value(response_payload, "name")
        )
        if tool_name is None:
            tool_name = string_payload_value(request_payload, "name")
        if tool_name is not None:
            api_cache.invalidate_tool(tool_name)
    elif parts[UPSTREAM_KIND_INDEX] == "lists":
        list_id = (
            parts[UPSTREAM_OBJECT_INDEX]
            if len(parts) >= UPSTREAM_OBJECT_PARTS
            else string_payload_value(response_payload, "id")
        )
        if list_id is not None:
            api_cache.invalidate_list(list_id)
        else:
            api_cache.invalidate_list_collection()


def json_object_body() -> tuple[dict | None, Response | None]:
    """Return the request JSON object or a normalized 400 response."""
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return None, bad("body must be a JSON object")
    return value, None


def safe_failure_activity_payload(payload: dict) -> dict:
    """Keep fallback activity queryable without publishing submitted values."""
    response = payload.get("toolhubResponse")
    response = response if isinstance(response, dict) else {}
    safe = {
        "syncStatus": SYNC_LOCAL_FALLBACK,
        "httpStatus": payload.get("_toolhubStatus") or response.get("status_code") or response.get("status"),
        "toolhubCode": payload.get("_toolhubCode") or response.get("code"),
        "lastError": payload.get("lastError"),
    }
    local = payload.get("local")
    if isinstance(local, dict):
        meta = set(META_KEYS) | {"id", "name", "deleted"}
        safe["submittedFields"] = sorted(key for key in local if key not in meta)
    return {key: value for key, value in safe.items() if value not in (None, "", [])}


def emit_structured_activity(  # noqa: PLR0913 - activity rows need explicit queryable fields
    s: Any,  # noqa: ANN401 - SQLAlchemy Session
    user: User,
    *,
    action: str,
    object_type: str,
    object_key: str,
    official_status: str,
    payload: dict,
    title: str | None = None,
) -> None:
    """Add Evolved activity in both legacy feed shapes plus structured columns."""
    stored_payload = safe_failure_activity_payload(payload) if official_status == SYNC_LOCAL_FALLBACK else payload
    now = utcnow()
    client_id = f"w{uuid4().hex}"
    label = title or object_key
    common_row = {
        "id": client_id,
        "timestamp": iso(now),
        "user": {"username": user.username},
        "_evolved": True,
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
        "officialStatus": official_status,
    }
    rows = {
        "revisions": {
            **common_row,
            "comment": f"Evolved: {action}",
            "content_type": object_type,
            "content_id": object_key,
            "content_title": label,
        },
        "auditlogs": {
            **common_row,
            "action": action,
            "target": {"type": object_type, "id": object_key, "label": label},
        },
    }
    for kind, row in rows.items():
        s.add(
            ActivityRow(
                kind=kind,
                client_id=client_id,
                user_id=user.id,
                created_by_user_id=user.id,
                row=row,
                created_at=now,
                object_type=object_type,
                object_key=object_key,
                action=action,
                official_status=official_status,
                payload=stored_payload,
                source=SOURCE_LOCAL,
                sync_status=SYNC_EVOLVED_REAL,
                last_synced_at=now if official_status == SYNC_OFFICIAL else None,
                last_error=clean_error(stored_payload.get("lastError")),
            )
        )


def claim_tool_or_error(name: str) -> tuple[dict | None, Response | None]:
    """Load one canonical Toolhub record for a claim operation."""
    cleaned = clean_name(name)
    if cleaned is None:
        return None, bad("tool name is required")
    try:
        tool = toolhub_tool_detail(cleaned)
    except (toolhub.ToolhubAPIError, toolhub.requests.RequestException) as exc:
        return None, deny(HTTP_BAD_GATEWAY, clean_error(str(exc)) or "official Toolhub is unavailable")
    if tool is None or clean_name(tool.get("name")) != cleaned:
        return None, deny(HTTP_NOT_FOUND, "canonical Toolhub tool not found")
    return tool, None


def create_control_challenge(
    s: Session,
    user: User,
    tool_name: str,
    toolinfo_url: str,
) -> tuple[ToolinfoControlChallenge | None, Response | None]:
    url_error = url_validation_message(toolinfo_url, label="toolinfo URL")
    if url_error is not None:
        return None, url_validation_bad("toolinfoUrl", url_error)
    try:
        fetch_matching_item(toolinfo_url, tool_name)
    except Exception as exc:  # noqa: BLE001 - normalize bounded external proof failures
        return None, bad(
            f"Could not read {tool_name} from the supplied toolinfo URL: {clean_error(str(exc)) or 'fetch failed'}"
        )
    now = utcnow()
    row = ToolinfoControlChallenge(
        user_id=user.id,
        tool_name=tool_name,
        toolinfo_url=toolinfo_url,
        challenge_token=new_token(),
        status=CHALLENGE_STATUS_PENDING,
        created_at=now,
        expires_at=now + CHALLENGE_TTL,
    )
    s.add(row)
    s.flush()
    return row, None


def verify_control_challenge_record(
    s: Session,
    user: User,
    row: ToolinfoControlChallenge,
) -> tuple[ToolAuthorClaim | None, Response | None]:
    """Verify one URL-control challenge and update its workflow claim."""
    if row.status != CHALLENGE_STATUS_VERIFIED and challenge_expired(row):
        row.status = CHALLENGE_STATUS_EXPIRED
        row.last_checked_at = utcnow()
        row.last_error = "challenge expired; create a new challenge"
        return None, deny(HTTP_CONFLICT, "ownership challenge expired; create a new challenge")
    if row.status != CHALLENGE_STATUS_VERIFIED:
        try:
            item = fetch_matching_item(row.toolinfo_url, row.tool_name)
        except Exception as exc:  # noqa: BLE001 - keep the challenge pending with an actionable reason
            row.last_checked_at = utcnow()
            row.last_error = clean_error(str(exc)) or "toolinfo fetch failed"
            return None, bad(f"Could not verify the toolinfo URL: {row.last_error}")
        metadata = item.get("x_toolhub_evolved_verification")
        token = metadata.get("challenge") if isinstance(metadata, dict) else None
        if token != row.challenge_token:
            row.last_checked_at = utcnow()
            row.last_error = f"{CHALLENGE_FIELD} did not contain the issued challenge"
            return None, bad(
                f"Publish the issued token in {CHALLENGE_FIELD}, then try again.",
                [{"field": CHALLENGE_FIELD, "message": "challenge token did not match"}],
            )
    now = utcnow()
    claim = record_author_claim(
        s,
        tool_name=row.tool_name,
        author_name=user.username,
        toolhub_username=user.username,
        user_id=user.id,
        verification_status=AUTHOR_CLAIM_VERIFIED,
        verification_method=AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_url=row.toolinfo_url,
        evidence_payload={"challengeId": row.id, "field": CHALLENGE_FIELD, "proof": "url_control"},
        expires_at=now + CONTROL_CLAIM_TTL,
    )
    row.status = CHALLENGE_STATUS_VERIFIED
    row.verified_at = row.verified_at or now
    row.last_checked_at = now
    row.last_error = None
    maintainer_index.sync_author_claim_edges(s, tool_names=[row.tool_name], user_ids=[user.id])
    return claim, None


ME_TOOLS_SUMMARY_LIMIT = 50


def profile_payload(profile: PersonProfile | None, person: Person) -> dict[str, Any]:
    return {
        "personId": person.public_id,
        "displayName": person.display_name,
        "bio": profile.bio if profile is not None else "",
        "avatarUrl": profile.avatar_url if profile is not None else "",
        "websiteUrl": profile.website_url if profile is not None else "",
        "location": profile.location if profile is not None else "",
        "links": profile.links if profile is not None and isinstance(profile.links, list) else [],
        "visibility": profile.visibility if profile is not None else "public",
        "updatedAt": iso(profile.updated_at) if profile is not None else "",
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
    }


def merged_maps(kind_rows: list[Any], viewer_uid: int | None = None) -> dict[str, dict]:
    """Merge rows (any user) into {tool_name: payload}.

    Rows arrive oldest first, so the most recently modified contribution wins
    each name.
    """
    out: dict[str, dict] = {}
    for row in kind_rows:
        if isinstance(row, ToolOverlay):
            payload = with_common_meta(row.patch if isinstance(row.patch, dict) else {}, row)
            if row.base_revision:
                payload["baseRevision"] = row.base_revision
            if row.field_statuses:
                payload["fieldStatuses"] = row.field_statuses
            if row.review_status:
                payload["reviewStatus"] = row.review_status
            if viewer_uid is not None:
                viewer_owned = row.user_id == viewer_uid
                payload["viewerOwned"] = viewer_owned
                if not viewer_owned:
                    for key in ("lastError", "toolhubResponse", "validationErrors"):
                        payload.pop(key, None)
            out[row.tool_name] = payload
        else:
            out[row.tool_name] = row.record
    return out


def assemble_overlay(uid: int) -> dict[str, Any]:
    with db.session_scope() as s:
        favorites = [
            f.tool_name
            for f in s.execute(select(Favorite).where(Favorite.user_id == uid).order_by(Favorite.position)).scalars()
        ]
        lists = [
            list_payload(row)
            for row in s.execute(
                select(ToolList)
                .where(ToolList.user_id == uid, ToolList.deleted_at.is_(None))
                .order_by(ToolList.created_at.desc())
            ).scalars()
        ]
        crawler_urls = [
            crawler_url_payload(c)
            for c in s.execute(
                select(CrawlerUrl)
                .where(CrawlerUrl.user_id == uid, CrawlerUrl.enabled.is_(True))
                .order_by(CrawlerUrl.added_at.desc())
            ).scalars()
        ]
        overlays = {
            key: merged_maps(
                list(
                    s.execute(
                        select(ToolOverlay).where(ToolOverlay.kind == kind).order_by(ToolOverlay.modified_at)
                    ).scalars()
                ),
                viewer_uid=uid,
            )
            for key, kind in OVERLAY_KINDS.items()
        }
        tool_new = {}
        for row in s.execute(
            select(ToolRecord)
            .where(
                ToolRecord.deleted_at.is_(None),
                or_(ToolRecord.user_id == uid, ToolRecord.visibility == VISIBILITY_PUBLIC),
            )
            .order_by(ToolRecord.modified_at)
        ).scalars():
            if row.user_id != uid and not local_tool_is_public(row):
                continue
            record = tool_record_payload(row)
            record["viewerOwned"] = row.user_id == uid
            if not record["viewerOwned"]:
                for key in ("lastError", "toolhubResponse", "validationErrors"):
                    record.pop(key, None)
            tool_new[row.tool_name] = record
        feeds = {
            key: activity_privacy.public_activity_rows(
                [
                    r.row
                    for r in s.execute(
                        select(ActivityRow)
                        .where(ActivityRow.kind == key)
                        .order_by(ActivityRow.created_at.desc(), ActivityRow.id.desc())
                        .limit(FEED_READ_CAP)
                    ).scalars()
                ]
            )
            for key in FEED_KEYS
        }
    return {
        "favorites": favorites,
        "lists": lists,
        "crawlerUrls": crawler_urls,
        "toolNew": tool_new,
        **overlays,
        **feeds,
    }


MAX_DESCRIPTION = 5000


MAX_URL = 2000


STR_LIST_FIELDS = ("keywords", "forWikis", "uiLanguages")


OPT_STR_FIELDS = ("repository", "license", "toolType")


def clean_tool_record(rec: dict) -> dict | None:
    """Validate + whitelist a toolNew record; None when it can't be a tool.

    The stored shape is exactly what the public feed and search render, so a
    signed-in client must never be able to persist a record that breaks them
    (missing url, non-list keywords, …).
    """
    title, description, url = rec.get("title"), rec.get("description"), rec.get("url")
    text_ok = isinstance(title, str) and title.strip() and isinstance(description, str)
    if not (text_ok and isinstance(url, str) and url.startswith("https://")):
        return None
    clean: dict[str, Any] = {
        "title": title[:MAX_NAME],
        "description": description[:MAX_DESCRIPTION],
        "url": url[:MAX_URL],
        "deprecated": bool(rec.get("deprecated")),
        "experimental": bool(rec.get("experimental")),
        "origin": "crawler" if rec.get("origin") == "crawler" else "api",
    }
    for field in OPT_STR_FIELDS:
        raw = rec.get(field)
        clean[field] = raw[:MAX_NAME] if isinstance(raw, str) and raw else None
    for field in STR_LIST_FIELDS:
        raw = rec.get(field)
        items = raw if isinstance(raw, list) else []
        clean[field] = [str(item)[:MAX_NAME] for item in items[:50] if isinstance(item, str | int | float)]
    return clean


def data_patch(patch: dict) -> dict:
    """Remove lifecycle metadata before merging a local overlay into a tool."""
    return {k: v for k, v in patch.items() if k not in META_KEYS and k not in CANONICAL_TOOL_KEYS}
