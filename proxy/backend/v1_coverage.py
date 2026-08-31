# SPDX-License-Identifier: GPL-3.0-or-later
"""Field-level catalog filling, broken down by the source that supplied each value."""

from flask import Blueprint, Response

from backend import catalog_coverage
from backend import v1_common as common

v1_coverage_bp = Blueprint("v1_coverage", __name__)


@v1_coverage_bp.route("/v1/coverage/")
def v1_coverage() -> Response:
    """Return one cacheable, database-local field-coverage snapshot."""
    return common.public_json_response(catalog_coverage.snapshot(), max_age=300)
