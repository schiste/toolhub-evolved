# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived maintainer graph and local activity rollups.

This module does not define canonical maintainer truth. It consolidates public
Toolhub metadata, Toolforge/signed-toolinfo/write-access author claims, and
local Evolved activity into auditable summaries that can feed health scoring.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select

from backend.author_claims import dedupe_strings
from backend.models import (
    ActivityRow,
    CrawlerUrl,
    MaintainerActivityRollup,
    SourceAnalysisReport,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolList,
    ToolMaintainerEdge,
    ToolOverlay,
    ToolRecord,
    User,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_FAILED,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_STALE,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_UNVERIFIED,
    AUTHOR_CLAIM_VERIFIED,
    SOURCE_LOCAL,
    SOURCE_OFFICIAL,
    SYNC_EVOLVED_REAL,
    clean_author_claim_method,
    clean_author_claim_status,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SOURCE_AUTHOR_CLAIM = "evolved_author_claim"
SOURCE_TOOLHUB_AUTHOR = "toolhub_author_metadata"
SOURCE_TOOLHUB_ACTOR = "toolhub_catalog_actor"
METHOD_TOOLHUB_AUTHOR = "toolhub_author_metadata"
METHOD_TOOLHUB_ACTOR = "toolhub_catalog_actor"
ACTIVE_DAYS = 90
QUIET_DAYS = 365
STALE_DAYS = 730
RECENT_ACTIVITY_DAYS = 90
ROLLUP_STALE_DAYS = 7
MAX_PUBLIC_MAINTAINERS = 20
VERIFIED_CONFIDENCE_MIN = 70
VERIFIED_STATUS_CONFIDENCE_MIN = 85

CLAIM_CONFIDENCE = {
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER: 95,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS: 90,
    AUTHOR_CLAIM_SIGNED_TOOLINFO: 88,
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME: 35,
}
STATUS_MULTIPLIER = {
    AUTHOR_CLAIM_VERIFIED: 1.0,
    AUTHOR_CLAIM_STALE: 0.65,
    AUTHOR_CLAIM_UNVERIFIED: 0.55,
    AUTHOR_CLAIM_FAILED: 0.0,
}


def clean_text(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - untrusted API/user JSON
    """Return a bounded stripped string."""
    return str(value or "").strip()[:limit]


def maintainer_key(*, toolhub_username: str = "", wiki_username: str = "", display_name: str = "") -> str:
    """Return a stable, namespaced maintainer key."""
    if toolhub_username:
        return f"toolhub:{toolhub_username.casefold()}"
    if wiki_username:
        return f"wiki:{wiki_username.casefold()}"
    return f"author:{display_name.casefold()}"


def _claim_status(row: ToolAuthorClaim) -> str:
    status = clean_author_claim_status(row.verification_status)
    if status == AUTHOR_CLAIM_VERIFIED and row.expires_at is not None and row.expires_at <= utcnow():
        return AUTHOR_CLAIM_STALE
    return status


def _claim_confidence(row: ToolAuthorClaim) -> int:
    method = clean_author_claim_method(row.verification_method)
    status = _claim_status(row)
    return round(CLAIM_CONFIDENCE.get(method, 20) * STATUS_MULTIPLIER.get(status, 0.5))


def _claim_edge_identity(row: ToolAuthorClaim) -> tuple[str, str, str, str]:
    """Return the public maintainer edge identity a claim writes to."""
    username = clean_text(row.toolhub_username)
    author_name = clean_text(row.author_name)
    return (
        clean_text(row.tool_name),
        maintainer_key(toolhub_username=username, display_name=author_name),
        SOURCE_AUTHOR_CLAIM,
        clean_author_claim_method(row.verification_method),
    )


def _claim_rank(row: ToolAuthorClaim) -> tuple[int, datetime]:
    """Return a deterministic freshness-aware rank for duplicate public edges."""
    return (_claim_confidence(row), row.checked_at or datetime.min)


def _best_claim_rows(rows: list[ToolAuthorClaim]) -> list[ToolAuthorClaim]:
    """Collapse raw claims to the strongest claim for each public edge identity."""
    best: dict[tuple[str, str, str, str], ToolAuthorClaim] = {}
    for row in rows:
        identity = _claim_edge_identity(row)
        current = best.get(identity)
        if current is None or _claim_rank(row) > _claim_rank(current):
            best[identity] = row
    return [best[key] for key in sorted(best)]


def _edge_status(confidences: list[int]) -> str:
    if not confidences:
        return "unknown"
    best = max(confidences)
    if best >= VERIFIED_STATUS_CONFIDENCE_MIN:
        return "verified"
    if best >= VERIFIED_CONFIDENCE_MIN:
        return "probable"
    return "candidate"


def _activity_status(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= ACTIVE_DAYS:
        return "active"
    if age_days <= QUIET_DAYS:
        return "quiet"
    if age_days <= STALE_DAYS:
        return "stale"
    return "dormant"


def _upsert_edge(  # noqa: PLR0913 - maintainer edges intentionally carry explicit provenance fields.
    s: Session,
    *,
    tool_name: str,
    key: str,
    display_name: str,
    toolhub_username: str = "",
    author_name: str = "",
    source: str,
    method: str,
    verification_status: str,
    confidence: int,
    evidence_url: str | None = None,
    evidence_payload: dict | None = None,
    checked_at: Any = None,  # noqa: ANN401 - SQLAlchemy datetime field passthrough
    expires_at: Any = None,  # noqa: ANN401 - SQLAlchemy datetime field passthrough
    last_error: str | None = None,
) -> ToolMaintainerEdge:
    """Upsert one maintainer edge."""
    now = utcnow()
    row = s.execute(
        select(ToolMaintainerEdge).where(
            ToolMaintainerEdge.tool_name == tool_name,
            ToolMaintainerEdge.maintainer_key == key,
            ToolMaintainerEdge.source == source,
            ToolMaintainerEdge.method == method,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ToolMaintainerEdge(
            tool_name=tool_name,
            maintainer_key=key,
            source=source,
            method=method,
            first_seen_at=now,
        )
        s.add(row)
    row.maintainer_display_name = display_name
    row.toolhub_username = toolhub_username
    row.author_name = author_name
    row.verification_status = verification_status
    row.confidence = max(0, min(100, confidence))
    row.evidence_url = evidence_url[:2000] if evidence_url else None
    row.evidence_payload = evidence_payload
    row.checked_at = checked_at or now
    row.expires_at = expires_at
    row.last_error = last_error[:2000] if last_error else None
    return row


def upsert_edge_from_claim(s: Session, row: ToolAuthorClaim) -> ToolMaintainerEdge:
    """Upsert an edge from one existing author claim."""
    username = clean_text(row.toolhub_username)
    author_name = clean_text(row.author_name)
    display = username or author_name
    return _upsert_edge(
        s,
        tool_name=clean_text(row.tool_name),
        key=maintainer_key(toolhub_username=username, display_name=author_name),
        display_name=display,
        toolhub_username=username,
        author_name=author_name,
        source=SOURCE_AUTHOR_CLAIM,
        method=clean_author_claim_method(row.verification_method),
        verification_status=_claim_status(row),
        confidence=_claim_confidence(row),
        evidence_url=row.evidence_url,
        evidence_payload=row.evidence_payload,
        checked_at=row.checked_at,
        expires_at=row.expires_at,
        last_error=row.last_error,
    )


def sync_author_claim_edges(
    s: Session, *, tool_names: list[str] | None = None, usernames: list[str] | None = None
) -> list[ToolMaintainerEdge]:
    """Refresh maintainer edges from stored Evolved author claims."""
    query = select(ToolAuthorClaim)
    if tool_names:
        query = query.where(ToolAuthorClaim.tool_name.in_(tool_names))
    if usernames:
        query = query.where(ToolAuthorClaim.toolhub_username.in_(usernames))
    rows = _best_claim_rows(list(s.execute(query).scalars()))
    edges = [upsert_edge_from_claim(s, row) for row in rows]
    refresh_activity_rollups(s, maintainer_keys=[edge.maintainer_key for edge in edges])
    return edges


def _toolhub_author_rows(tool: dict) -> list[dict[str, str]]:
    raw_authors = tool.get("author")
    authors = raw_authors if isinstance(raw_authors, list) else [raw_authors]
    rows: list[dict[str, str]] = []
    for author in authors:
        if isinstance(author, dict):
            display = clean_text(author.get("name") or author.get("developer_username") or author.get("wiki_username"))
            developer = clean_text(author.get("developer_username"))
            wiki = clean_text(author.get("wiki_username"))
            if display:
                rows.append({"display": display, "toolhub": developer, "wiki": wiki, "method": METHOD_TOOLHUB_AUTHOR})
        elif isinstance(author, str | int | float):
            display = clean_text(author)
            if display:
                rows.append({"display": display, "toolhub": "", "wiki": "", "method": METHOD_TOOLHUB_AUTHOR})
    for actor_key in ("created_by", "modified_by"):
        actor = tool.get(actor_key)
        if isinstance(actor, dict):
            username = clean_text(actor.get("username"))
            if username:
                rows.append({"display": username, "toolhub": username, "wiki": "", "method": METHOD_TOOLHUB_ACTOR})
    return rows


def replace_toolhub_metadata_edges(s: Session, tool_name: str, tool: dict) -> list[ToolMaintainerEdge]:
    """Replace weak official Toolhub metadata edges for one tool."""
    clean_tool_name = clean_text(tool_name or tool.get("name"))
    if not clean_tool_name:
        return []
    s.execute(
        delete(ToolMaintainerEdge).where(
            ToolMaintainerEdge.tool_name == clean_tool_name,
            ToolMaintainerEdge.source.in_({SOURCE_TOOLHUB_AUTHOR, SOURCE_TOOLHUB_ACTOR}),
        )
    )
    edges: list[ToolMaintainerEdge] = []
    for row in _toolhub_author_rows(tool):
        source = SOURCE_TOOLHUB_ACTOR if row["method"] == METHOD_TOOLHUB_ACTOR else SOURCE_TOOLHUB_AUTHOR
        confidence = 55 if source == SOURCE_TOOLHUB_ACTOR else 45
        edges.append(
            _upsert_edge(
                s,
                tool_name=clean_tool_name,
                key=maintainer_key(
                    toolhub_username=row["toolhub"],
                    wiki_username=row["wiki"],
                    display_name=row["display"],
                ),
                display_name=row["display"],
                toolhub_username=row["toolhub"],
                author_name=row["display"],
                source=source,
                method=row["method"],
                verification_status=AUTHOR_CLAIM_UNVERIFIED,
                confidence=confidence,
                evidence_payload={"toolhubToolName": clean_tool_name},
            )
        )
    refresh_activity_rollups(s, maintainer_keys=[edge.maintainer_key for edge in edges])
    return edges


def _toolhub_usernames_for_keys(keys: set[str]) -> set[str]:
    return {key.split(":", 1)[1] for key in keys if key.startswith("toolhub:")}


def _activity_dates_for_user(s: Session, user: User) -> list[Any]:
    dates: list[Any] = [user.registered_at]
    activity_sources = (
        select(ToolList.modified_at).where(ToolList.user_id == user.id),
        select(ToolRecord.modified_at).where(ToolRecord.user_id == user.id),
        select(ToolOverlay.modified_at).where(ToolOverlay.user_id == user.id),
        select(ActivityRow.created_at).where(ActivityRow.user_id == user.id),
        select(CrawlerUrl.added_at).where(CrawlerUrl.user_id == user.id),
        select(SourceAnalysisReport.created_at).where(SourceAnalysisReport.user_id == user.id),
        select(ToolAuthorKey.last_used_at).where(ToolAuthorKey.toolhub_username == user.username),
        select(ToolAuthorKey.created_at).where(ToolAuthorKey.toolhub_username == user.username),
    )
    for query in activity_sources:
        dates.extend(row[0] for row in s.execute(query).all() if row[0] is not None)
    return dates


def _rollup_for_key(s: Session, key: str) -> MaintainerActivityRollup:
    username = key.split(":", 1)[1] if key.startswith("toolhub:") else ""
    users = []
    if username:
        users = list(s.execute(select(User).where(func.lower(User.username) == username.casefold())).scalars())
    dates: list[Any] = []
    display = username
    for user in users:
        display = user.username
        dates.extend(_activity_dates_for_user(s, user))
    now = utcnow()
    recent_after = now - timedelta(days=RECENT_ACTIVITY_DAYS)
    recent_count = sum(1 for value in dates if value is not None and value >= recent_after)
    last_activity = max(dates) if dates else None
    age_days = (now - last_activity).days if last_activity is not None else None
    edges = list(s.execute(select(ToolMaintainerEdge).where(ToolMaintainerEdge.maintainer_key == key)).scalars())
    active_tool_count = len({edge.tool_name for edge in edges})
    verified_tool_count = len(
        {
            edge.tool_name
            for edge in edges
            if edge.verification_status == AUTHOR_CLAIM_VERIFIED and edge.confidence >= VERIFIED_CONFIDENCE_MIN
        }
    )
    row = s.get(MaintainerActivityRollup, key)
    if row is None:
        row = MaintainerActivityRollup(maintainer_key=key)
        s.add(row)
    row.maintainer_display_name = display or (edges[0].maintainer_display_name if edges else "")
    row.toolhub_username = display if username else ""
    row.source = SOURCE_LOCAL
    row.active_tool_count = active_tool_count
    row.verified_tool_count = verified_tool_count
    row.recent_activity_count = recent_count
    row.last_activity_at = last_activity
    row.activity_status = _activity_status(age_days)
    row.computed_at = now
    row.stale_at = now + timedelta(days=ROLLUP_STALE_DAYS)
    return row


def refresh_activity_rollups(s: Session, *, maintainer_keys: list[str] | None = None) -> list[MaintainerActivityRollup]:
    """Refresh local activity rollups for known maintainer keys."""
    if maintainer_keys is None:
        keys = set()
        keys.update(row[0] for row in s.execute(select(ToolMaintainerEdge.maintainer_key).distinct()))
        keys.update(f"toolhub:{row[0].casefold()}" for row in s.execute(select(User.username)).all() if row[0])
    else:
        keys = set(maintainer_keys)
    keys.update(f"toolhub:{username.casefold()}" for username in _toolhub_usernames_for_keys(keys))
    return [_rollup_for_key(s, key) for key in sorted(keys) if key]


def activity_payload(row: MaintainerActivityRollup | None) -> dict:
    """Public-safe activity rollup payload."""
    if row is None:
        return {"status": "unknown"}
    age_days = (utcnow() - row.last_activity_at).days if row.last_activity_at is not None else None
    return {
        "status": row.activity_status or "unknown",
        "lastActivityAgeDays": age_days,
        "recentActivityCount": row.recent_activity_count,
        "activeToolCount": row.active_tool_count,
        "verifiedToolCount": row.verified_tool_count,
        "computedAt": row.computed_at.isoformat(timespec="seconds") + "Z" if row.computed_at else "",
    }


def public_edge_payload(edge: ToolMaintainerEdge, activity: MaintainerActivityRollup | None = None) -> dict:
    """Public-safe maintainer edge payload without raw evidence."""
    return {
        "displayName": edge.maintainer_display_name,
        "toolhubUsername": edge.toolhub_username,
        "verificationStatus": edge.verification_status,
        "confidence": edge.confidence,
        "source": edge.source,
        "method": edge.method,
        "activity": activity_payload(activity),
    }


def public_tool_summary(s: Session, tool_name: str) -> dict:
    """Return a public-safe maintainer summary for one tool."""
    clean_tool_name = clean_text(tool_name)
    edges = list(
        s.execute(
            select(ToolMaintainerEdge)
            .where(ToolMaintainerEdge.tool_name == clean_tool_name)
            .order_by(ToolMaintainerEdge.confidence.desc(), ToolMaintainerEdge.maintainer_display_name)
        ).scalars()
    )
    rollups = {
        row.maintainer_key: row
        for row in s.execute(
            select(MaintainerActivityRollup).where(
                MaintainerActivityRollup.maintainer_key.in_({edge.maintainer_key for edge in edges} or {""})
            )
        ).scalars()
    }
    grouped: dict[str, dict[str, Any]] = {}
    for edge in edges:
        current = grouped.setdefault(
            edge.maintainer_key,
            {
                "edge": edge,
                "confidence": edge.confidence,
                "methods": [],
            },
        )
        if edge.confidence > current["confidence"]:
            current["edge"] = edge
            current["confidence"] = edge.confidence
        current["methods"].append(edge.method)
    maintainers = []
    active_count = 0
    verified_count = 0
    for key, item in sorted(grouped.items(), key=lambda row: (-int(row[1]["confidence"]), row[0])):
        edge = item["edge"]
        activity = rollups.get(key)
        payload = public_edge_payload(edge, activity)
        payload["methods"] = dedupe_strings(item["methods"])
        maintainers.append(payload)
        if payload["verificationStatus"] == AUTHOR_CLAIM_VERIFIED and payload["confidence"] >= VERIFIED_CONFIDENCE_MIN:
            verified_count += 1
        if payload["activity"].get("status") in {"active", "quiet"}:
            active_count += 1
    confidences = [edge.confidence for edge in edges]
    return {
        "toolName": clean_tool_name,
        "status": _edge_status(confidences),
        "counts": {
            "maintainers": len(maintainers),
            "verifiedMaintainers": verified_count,
            "activeMaintainers": active_count,
            "evidenceEdges": len(edges),
        },
        "bestConfidence": max(confidences) if confidences else 0,
        "maintainers": maintainers[:MAX_PUBLIC_MAINTAINERS],
        "publicDataPolicy": {
            "canonical": False,
            "evidence": "private",
            "summary": "Derived Evolved maintainer summary built from Toolhub, Toolforge, and Evolved evidence.",
        },
        "source": SOURCE_OFFICIAL if any(edge.source.startswith("toolhub") for edge in edges) else SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
    }
