# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/crawler/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from flask import Blueprint, Response, jsonify
from sqlalchemy import select

from backend import (
    authz,
    db,
    toolinfo_discovery,
    v1,
)
from backend.models import (
    CrawlerRun,
)
from backend.security import login_required, write_guard
from backend.sync import (
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
)

v1_crawler_bp = Blueprint("v1_crawler", __name__)


@v1_crawler_bp.route("/v1/crawler/toolinfo-discovery/", methods=["POST"])
@write_guard
def discover_toolinfo_url() -> Response:
    """Find a toolinfo.json URL from a tool homepage/root URL."""
    value, err = v1._json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    raw_url = v1._payload_value(value, "url", "baseUrl")
    error = v1._url_validation_message(raw_url, label="tool URL")
    if error is not None:
        return v1._url_validation_bad("url", error)
    v1._require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    return jsonify(toolinfo_discovery.discover_toolinfo_url(str(raw_url)))


@v1_crawler_bp.route("/v1/crawler/runs/")
@login_required
def v1_crawler_runs() -> Response:
    """Recent local crawler job outcomes for signed-in contributors."""
    with db.session_scope() as s:
        runs = [
            {
                "id": row.id,
                "startedAt": v1._iso(row.started_at),
                "endedAt": v1._iso(row.ended_at),
                "urlsCount": row.urls_count,
                "added": row.added,
                "updated": row.updated,
                "ok": row.ok,
                "errors": row.errors if isinstance(row.errors, list) else [],
                "source": row.source or SOURCE_LOCAL,
                "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
            }
            for row in s.execute(
                select(CrawlerRun).order_by(CrawlerRun.started_at.desc(), CrawlerRun.id.desc()).limit(20)
            ).scalars()
        ]
    return jsonify({"count": len(runs), "results": runs})
