# SPDX-License-Identifier: GPL-3.0-or-later
# cspell:words favourite favourites favourited unfavorited unfavourited
"""Public-feed privacy rules for user preference activity."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

PUBLIC_ACTIVITY_PATHS = {"/api/recent", "/api/auditlogs"}
PRIVATE_OBJECT_KEYS = {"favorite", "favorites", "favourite", "favourites", "user_favorite", "user_favourite"}
PRIVATE_ACTION_KEYS = {
    "favorited",
    "favourited",
    "unfavorited",
    "unfavourited",
    "favorite_removed",
    "favourite_removed",
    "favorite_retried",
    "favorite_retry_failed",
    "favorite_discarded",
}
_NON_WORD_CHARS = re.compile(r"[^a-z0-9]+")


def _key(value: Any) -> str:  # noqa: ANN401 - activity JSON is untrusted
    return _NON_WORD_CHARS.sub("_", str(value or "").strip().lower()).strip("_")


def _target_type(row: dict[str, Any]) -> Any:  # noqa: ANN401 - normalized by _key
    target = row.get("target")
    return target.get("type") if isinstance(target, dict) else None


def is_private_preference_activity(row: object) -> bool:
    """Return whether one activity row reveals a favorite preference."""
    if not isinstance(row, dict):
        return False
    object_keys = {_key(row.get("content_type")), _key(row.get("object_type")), _key(_target_type(row))}
    if any(key in PRIVATE_OBJECT_KEYS or "favorite" in key or "favourite" in key for key in object_keys if key):
        return True
    action_keys = {_key(row.get("action")), _key(row.get("comment"))}
    for key in action_keys:
        if key in PRIVATE_ACTION_KEYS:
            return True
        preference_word = "favorite" in key or "favourite" in key
        preference_action = any(
            token in key for token in ("add", "remove", "favorited", "favourited", "unfavorited", "unfavourited")
        )
        if preference_word and preference_action:
            return True
    return False


def public_activity_rows(rows: object) -> list[dict[str, Any]]:
    """Return dictionary rows that are safe for shared activity surfaces."""
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and not is_private_preference_activity(row)]


def _filtered_json(payload: bytes, keys: tuple[str, ...]) -> bytes:
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return payload
    if not isinstance(data, dict):
        return payload
    changed = False
    for key in keys:
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        public = public_activity_rows(rows)
        if len(public) != len(rows):
            data[key] = public
            changed = True
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode() if changed else payload


def sanitize_public_api_payload(url: str, payload: bytes) -> bytes:
    """Strip private preferences from public Toolhub activity responses."""
    if urlparse(url).path.rstrip("/") not in PUBLIC_ACTIVITY_PATHS:
        return payload
    return _filtered_json(payload, ("results",))


def sanitize_overlay_payload(payload: bytes) -> bytes:
    """Strip private preferences from legacy shared overlay feed arrays."""
    return _filtered_json(payload, ("revisions", "auditlogs"))
