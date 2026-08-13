# SPDX-License-Identifier: GPL-3.0-or-later
"""Public catalog-quality statistics assembled from local projections."""

from flask import Blueprint, Response

from backend import catalog_statistics
from backend import v1_common as common

v1_statistics_bp = Blueprint("v1_statistics", __name__)


@v1_statistics_bp.route("/v1/statistics/")
def v1_statistics() -> Response:
    """Return one cacheable, database-local catalog quality snapshot."""
    return common.public_json_response(catalog_statistics.snapshot(), max_age=300)
