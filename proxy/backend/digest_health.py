# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared, set-based digest health projections for APIs and scheduled audits."""

from typing import Any

from sqlalchemy import func, select

from backend.models import DigestDelivery, DigestEdition


def status_counts(session: Any) -> dict[str, dict[str, int]]:  # noqa: ANN401 - SQLAlchemy session
    """Return grouped edition and delivery states without loading history."""
    editions = dict(session.execute(select(DigestEdition.status, func.count()).group_by(DigestEdition.status)).all())
    deliveries = dict(
        session.execute(select(DigestDelivery.status, func.count()).group_by(DigestDelivery.status)).all()
    )
    return {"editions": editions, "deliveries": deliveries}
