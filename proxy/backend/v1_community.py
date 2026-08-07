# SPDX-License-Identifier: GPL-3.0-or-later
"""Unified public directory endpoint."""

from urllib.parse import urlencode

from flask import Blueprint, Response, jsonify, request

from backend import community_search, db, people_index, security, v1
from backend import v1_common as common
from backend.sync import SOURCE_LOCAL, SYNC_EVOLVED_REAL, clean_int

v1_community_bp = Blueprint("v1_community", __name__)
ORDERINGS = {"relevance", "relationship", "recent", "name"}
VERIFICATIONS = {"verified", "unverified", "renewal_needed"}
ACTIVITIES = {"active", "quiet", "unknown"}
MAX_TEXT_LENGTH = 255


class InvalidCommunityQueryError(ValueError):
    """Raised when unified directory parameters are invalid."""


def _positive(name: str, default: int, maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    value = clean_int(raw)
    if value is None or value < 1:
        message = f"{name} must be a positive integer"
        raise InvalidCommunityQueryError(message)
    return min(value, maximum) if maximum else value


def _choice(name: str, allowed: set[str], default: str = "") -> str:
    value = str(request.args.get(name) or default).strip()
    if value and value not in allowed:
        message = f"unsupported {name}"
        raise InvalidCommunityQueryError(message)
    return value


def _page_url(page: int | None) -> str | None:
    if page is None:
        return None
    args = request.args.to_dict(flat=True)
    args["page"] = str(page)
    return f"{request.path}?{urlencode(args)}"


@v1_community_bp.route("/v1/community/")
def v1_community() -> Response:
    """Search identities, official accounts, tools, and unresolved labels together."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    query = str(request.args.get("q") or "").strip()
    project = str(request.args.get("project") or "").strip()
    if len(query) > MAX_TEXT_LENGTH or len(project) > MAX_TEXT_LENGTH:
        return common.bad("q and project must be 255 characters or fewer")
    try:
        search = community_search.CommunitySearchQuery(
            query=query,
            page=_positive("page", 1),
            page_size=_positive("page_size", 24, 100),
            role=_choice("role", set(people_index.PUBLIC_ROLES)),
            verification=_choice("verification", VERIFICATIONS),
            activity=_choice("activity", ACTIVITIES),
            project=project,
            ordering=_choice("ordering", ORDERINGS, "relevance"),
            contributor=_choice("contributor", {"observed"}) == "observed",
        )
    except InvalidCommunityQueryError as exc:
        return common.bad(str(exc))
    with db.session_scope() as s:
        payload = community_search.search_community(s, search)
    return jsonify(
        payload
        | {
            "next": _page_url(payload["nextPage"]),
            "previous": _page_url(payload["previousPage"]),
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "canonicalAuthority": {"accounts": "toolhub", "catalog": "toolhub", "profiles": "toolhub-evolved"},
        }
    )
