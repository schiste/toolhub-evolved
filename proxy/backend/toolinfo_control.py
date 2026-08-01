# SPDX-License-Identifier: GPL-3.0-or-later
"""Proof-of-control challenges for externally hosted toolinfo.json files."""

import secrets
from datetime import timedelta

from backend import toolinfo_discovery
from backend.models import ToolinfoControlChallenge, utcnow

CHALLENGE_FIELD = "x_toolhub_evolved_verification.challenge"
CHALLENGE_STATUS_PENDING = "pending"
CHALLENGE_STATUS_VERIFIED = "verified"
CHALLENGE_STATUS_EXPIRED = "expired"
CHALLENGE_TTL = timedelta(hours=24)
CONTROL_CLAIM_TTL = timedelta(days=30)


def new_token() -> str:
    """Create an unpredictable value suitable for publication in toolinfo."""
    return secrets.token_urlsafe(32)


def challenge_payload(row: ToolinfoControlChallenge, *, include_token: bool = True) -> dict:
    """Serialize a private challenge without exposing internal user ids."""
    payload = {
        "id": row.id,
        "toolName": row.tool_name,
        "toolinfoUrl": row.toolinfo_url,
        "status": row.status,
        "field": CHALLENGE_FIELD,
        "createdAt": row.created_at.isoformat(timespec="seconds") + "Z",
        "expiresAt": row.expires_at.isoformat(timespec="seconds") + "Z",
        "verifiedAt": row.verified_at.isoformat(timespec="seconds") + "Z" if row.verified_at else "",
        "lastCheckedAt": row.last_checked_at.isoformat(timespec="seconds") + "Z" if row.last_checked_at else "",
        "lastError": row.last_error or "",
    }
    if include_token and row.status == CHALLENGE_STATUS_PENDING:
        payload["token"] = row.challenge_token
    return payload


def matching_item(data: object, tool_name: str) -> dict | None:
    """Find exactly the named tool in an object or bounded toolinfo array."""
    items = [data] if isinstance(data, dict) else data[:200] if isinstance(data, list) else []
    for item in items:
        if isinstance(item, dict) and str(item.get("name") or "").strip() == tool_name:
            return item
    return None


def fetch_matching_item(url: str, tool_name: str) -> dict:
    """Fetch and validate one exact toolinfo URL for a challenge operation."""
    data = toolinfo_discovery.fetch_toolinfo_json_once(url)
    item = matching_item(data, tool_name)
    if item is None:
        message = f"{tool_name}: no matching item found at this toolinfo URL"
        raise ValueError(message)
    return item


def expired(row: ToolinfoControlChallenge) -> bool:
    return row.expires_at <= utcnow()
