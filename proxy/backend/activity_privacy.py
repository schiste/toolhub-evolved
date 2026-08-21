# SPDX-License-Identifier: GPL-3.0-or-later
# cspell:words favourite favourites favourited unfavorited unfavourited
"""Public-feed privacy rules for user preference and list activity."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

PUBLIC_ACTIVITY_PATHS = {"/api/recent", "/api/auditlogs"}
# Upstream Toolhub spells the list content type "toollist"; Evolved rows spell
# it "list".  Both reach these feeds, so both have to be recognized.
LIST_OBJECT_KEYS = {"list", "lists", "toollist", "toollists", "tool_list", "tool_lists"}
SYNC_OFFICIAL = "official"
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


def _content_id(row: dict[str, Any]) -> str:
    target = row.get("target")
    identifier = target.get("id") if isinstance(target, dict) else None
    if identifier is None:
        identifier = row.get("content_id")
    return "" if identifier is None else str(identifier).strip()


def _published_list_ids() -> frozenset[str]:
    """Return the allowlist, or an empty one when the replica cannot be read."""
    try:
        from backend import catalog_read  # noqa: PLC0415 - deferred; keeps this module import-light

        return catalog_read.published_list_ids()
    except Exception:  # noqa: BLE001 - an unreadable replica must fail closed, not leak
        return frozenset()


def is_private_list_activity(row: object) -> bool:
    """Return whether one list activity row names a list the public cannot see.

    Toolhub's recent-changes feed reports revisions for *every* list, including
    unpublished ones, so a row's own fields never say whether its list is
    public.  The decision is therefore made against a positive allowlist and
    fails closed: a list nobody can confirm as published stays out of the feed.

    Evolved's own rows are decided without the replica.  Evolved always writes
    lists upstream as published, so an officially-synced row is public by
    construction, while a local fallback describes a list that was never
    published anywhere.  Those rows also carry a local client id rather than an
    official list id, which the replica allowlist could never match.
    """
    if not isinstance(row, dict):
        return False
    object_keys = {_key(row.get("content_type")), _key(row.get("object_type")), _key(_target_type(row))}
    if not object_keys & LIST_OBJECT_KEYS:
        return False
    official_status = row.get("officialStatus")
    if row.get("_evolved") is True or official_status is not None:
        return official_status != SYNC_OFFICIAL
    content_id = _content_id(row)
    return not content_id or content_id not in _published_list_ids()


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


def is_private_activity(row: object) -> bool:
    """Return whether one activity row must stay out of every shared feed."""
    return is_private_preference_activity(row) or is_private_list_activity(row)


def public_activity_rows(rows: object) -> list[dict[str, Any]]:
    """Return dictionary rows that are safe for shared activity surfaces."""
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and not is_private_activity(row)]


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
