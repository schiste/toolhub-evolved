# SPDX-License-Identifier: GPL-3.0-or-later
"""Public status of the scheduled background workers."""

from flask import Blueprint, Response

from backend import db, workers
from backend import v1_common as common

v1_workers_bp = Blueprint("v1_workers", __name__)


@v1_workers_bp.route("/v1/workers/")
def v1_workers() -> Response:
    """Return every declared worker with its recent executed runs."""
    with db.session_scope() as session:
        payload = workers.snapshot(session)
    # Short cache: this is the page people open precisely when they suspect
    # something has stopped, so it must not answer with a stale all-clear.
    return common.public_json_response(payload, max_age=60)
