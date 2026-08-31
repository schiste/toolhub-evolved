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


@v1_workers_bp.route("/v1/workers/<name>/")
def v1_worker_detail(name: str) -> Response:
    """Return one worker with every run still retained, and what each one did."""
    with db.session_scope() as session:
        payload = workers.detail(session, name)
    if payload is None:
        # 404 rather than an empty worker: a name that is not in the catalogue
        # is a mistake somewhere, and answering it with a blank page would let
        # a renamed job look like one that has simply never run.
        return common.deny(common.HTTP_NOT_FOUND, "worker not found")
    return common.public_json_response(payload, max_age=60)
