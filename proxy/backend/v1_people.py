# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/people/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from urllib.parse import urlencode

from flask import Blueprint, Response, jsonify, request

from backend import (
    db,
    people_index,
    security,
    v1,
)
from backend import v1_common as common
from backend.sync import (
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
    clean_int,
)

v1_people_bp = Blueprint("v1_people", __name__)

PEOPLE_ORDERINGS = {"relevance", "relationship", "recent", "name"}
PEOPLE_VERIFICATION_FILTERS = {"verified", "unverified", "renewal_needed"}
PEOPLE_ACTIVITY_FILTERS = {"active", "quiet", "unknown"}
MAX_DIRECTORY_TEXT_LENGTH = 255


class InvalidPeopleQueryError(ValueError):
    """Raised when a public directory parameter is invalid."""


def _positive_arg(name: str, default: int, *, maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    value = clean_int(raw)
    if value is None or value < 1:
        message = f"{name} must be a positive integer"
        raise InvalidPeopleQueryError(message)
    return min(value, maximum) if maximum is not None else value


def _choice_arg(name: str, allowed: set[str], default: str = "") -> str:
    value = str(request.args.get(name) or default).strip()
    if value and value not in allowed:
        message = f"unsupported {name}"
        raise InvalidPeopleQueryError(message)
    return value


def _page_url(page: int | None) -> str | None:
    if page is None:
        return None
    args = request.args.to_dict(flat=True)
    legacy_size = args.pop("limit", None)
    if legacy_size and "page_size" not in args:
        args["page_size"] = legacy_size
    args["page"] = str(page)
    return f"{request.path}?{urlencode(args)}"


def _person_tool_page_url(page: int | None) -> str | None:
    if page is None:
        return None
    args = request.args.to_dict(flat=True)
    args["tool_page"] = str(page)
    return f"{request.path}?{urlencode(args)}"


@v1_people_bp.route("/v1/people/tools/<name>/")
def v1_tool_people(name: str) -> Response:
    """Read the local people projection for a canonical Toolhub tool."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    clean_name = common.clean_name(name)
    if clean_name is None:
        return common.bad("tool name is required")
    with db.session_scope() as s:
        return jsonify(people_index.public_people_summary(s, clean_name))


@v1_people_bp.route("/v1/people/")
def v1_people() -> Response:
    """Search public Evolved people without treating handles as stable ids."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    query = str(request.args.get("q") or "").strip()
    project = str(request.args.get("project") or "").strip()
    if len(query) > MAX_DIRECTORY_TEXT_LENGTH:
        return common.bad("q must be 255 characters or fewer")
    if len(project) > MAX_DIRECTORY_TEXT_LENGTH:
        return common.bad("project must be 255 characters or fewer")
    try:
        page = _positive_arg("page", 1)
        legacy_size = _positive_arg("limit", 24, maximum=100)
        page_size = _positive_arg("page_size", legacy_size, maximum=100)
        role = _choice_arg("role", set(people_index.PUBLIC_ROLES))
        verification = _choice_arg("verification", PEOPLE_VERIFICATION_FILTERS)
        activity = _choice_arg("activity", PEOPLE_ACTIVITY_FILTERS)
        ordering = _choice_arg("ordering", PEOPLE_ORDERINGS, "relevance")
    except InvalidPeopleQueryError as exc:
        return common.bad(str(exc))
    with db.session_scope() as s:
        payload = people_index.search_people_directory(
            s,
            people_index.PeopleDirectoryQuery(
                query=query,
                page=page,
                page_size=page_size,
                role=role,
                verification=verification,
                activity=activity,
                project=project,
                ordering=ordering,
            ),
        )
    return jsonify(
        payload
        | {
            "next": _page_url(payload["nextPage"]),
            "previous": _page_url(payload["previousPage"]),
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
        }
    )


@v1_people_bp.route("/v1/people/attributions/")
def v1_people_attributions() -> Response:
    """Search display-only labels without publishing them as people."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    query = str(request.args.get("q") or "").strip()
    project = str(request.args.get("project") or "").strip()
    if len(query) > MAX_DIRECTORY_TEXT_LENGTH:
        return common.bad("q must be 255 characters or fewer")
    if len(project) > MAX_DIRECTORY_TEXT_LENGTH:
        return common.bad("project must be 255 characters or fewer")
    try:
        page = _positive_arg("page", 1)
        page_size = _positive_arg("page_size", 10, maximum=100)
        role = _choice_arg("role", set(people_index.PUBLIC_ROLES))
    except InvalidPeopleQueryError as exc:
        return common.bad(str(exc))
    with db.session_scope() as s:
        payload = people_index.search_unresolved_attributions(
            s,
            people_index.UnresolvedAttributionQuery(
                query=query,
                page=page,
                page_size=page_size,
                role=role,
                project=project,
            ),
        )
    return jsonify(
        payload
        | {
            "next": _page_url(payload["nextPage"]),
            "previous": _page_url(payload["previousPage"]),
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
        }
    )


@v1_people_bp.route("/v1/people/resolve/")
def v1_people_resolve() -> Response:
    """Resolve a legacy name route only through one unique exact handle."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    handle = str(request.args.get("handle") or "").strip()
    if not handle:
        return common.bad("handle is required")
    with db.session_scope() as s:
        payload = people_index.resolve_legacy_handle(s, handle)
    return jsonify(
        payload
        | {
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
        }
    )


@v1_people_bp.route("/v1/people/<public_id>/")
def v1_person(public_id: str) -> Response:
    """Return one public person with one bounded local-only tool page."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    try:
        tool_page = _positive_arg("tool_page", 1)
        tool_page_size = _positive_arg("tool_page_size", 24, maximum=50)
    except InvalidPeopleQueryError as exc:
        return common.bad(str(exc))
    with db.session_scope() as s:
        payload = people_index.person_detail(
            s,
            public_id,
            people_index.PersonToolPage(page=tool_page, page_size=tool_page_size),
        )
    if payload is None:
        return common.deny(common.HTTP_NOT_FOUND, "person not found")
    payload["tools"]["next"] = _person_tool_page_url(payload["tools"]["nextPage"])
    payload["tools"]["previous"] = _person_tool_page_url(payload["tools"]["previousPage"])
    return jsonify(payload)
