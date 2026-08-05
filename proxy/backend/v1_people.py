# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/people/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from flask import Blueprint, Response, jsonify, request

from backend import (
    db,
    people_index,
    security,
    v1,
)
from backend.sync import (
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
    clean_int,
)

v1_people_bp = Blueprint("v1_people", __name__)


@v1_people_bp.route("/v1/people/tools/<name>/")
def v1_tool_people(name: str) -> Response:
    """Read the local people projection for a canonical Toolhub tool."""
    if security.read_rate_limited(request.remote_addr):
        return v1._deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    clean_name = v1._clean_name(name)
    if clean_name is None:
        return v1._bad("tool name is required")
    with db.session_scope() as s:
        return jsonify(people_index.public_people_summary(s, clean_name))


@v1_people_bp.route("/v1/people/")
def v1_people() -> Response:
    """Search public Evolved people without treating handles as stable ids."""
    if security.read_rate_limited(request.remote_addr):
        return v1._deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    query = str(request.args.get("q") or "").strip()
    limit = min(max(clean_int(request.args.get("limit")) or 50, 1), 100)
    with db.session_scope() as s:
        results = people_index.find_people(s, query, limit=limit)
    return jsonify(
        {
            "count": len(results),
            "results": results,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
        }
    )


@v1_people_bp.route("/v1/people/<public_id>/")
def v1_person(public_id: str) -> Response:
    """Return one public person, profile, tools, roles, and contribution summary."""
    if security.read_rate_limited(request.remote_addr):
        return v1._deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    with db.session_scope() as s:
        payload = people_index.person_detail(s, public_id)
    if payload is None:
        return v1._deny(v1.HTTP_NOT_FOUND, "person not found")
    return jsonify(payload)
