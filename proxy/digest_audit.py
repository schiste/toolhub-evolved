# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit digest publication and outbox health for Toolforge failure alerts."""

import os
from datetime import timedelta

from sqlalchemy import func, select

from backend import db, job_runner
from backend.digest_health import status_counts
from backend.digests import (
    ARCHIVE_STATE_KEY,
    OUT_OF_SCOPE_STATUS,
    PUBLICATION_BLOCKED_STATUS,
    PUBLICATION_FAILED_STATUS,
    clean_liftwing_endpoint,
    due_periods,
)
from backend.models import (
    DigestDelivery,
    DigestEdition,
    DigestOperationalState,
    DigestSubscription,
    ToolActivityEvent,
    utcnow,
)

MAX_VALIDATED_AGE = timedelta(hours=2)
MAX_OUTBOX_AGE = timedelta(hours=48)
MAX_DUE_PERIOD_AGE = timedelta(hours=8)
FALLBACK_ALERT_WINDOW = timedelta(hours=48)


class DigestAuditError(RuntimeError):
    """Raised when a durable digest backlog requires operator attention."""


def _liftwing_problems(*, has_activity: bool, recent_fallbacks: int) -> list[str]:
    """Return actionable production configuration and degradation problems."""
    endpoint = os.environ.get("LIFTWING_API_URL", "").strip()
    if has_activity and not endpoint:
        return ["LIFTWING_API_URL is not configured for Qwen editorial generation"]
    if not endpoint:
        return []
    if not os.environ.get("LIFTWING_MODEL", "").strip():
        return ["LIFTWING_MODEL is not configured with a public LiftWing Qwen model ID"]
    try:
        clean_liftwing_endpoint(endpoint, model=os.environ["LIFTWING_MODEL"].strip())
    except ValueError as exc:
        return [str(exc)]
    if recent_fallbacks:
        return ["one or more recent editions fell back instead of using Lift Wing Qwen"]
    return []


def audit() -> dict[str, object]:
    """Return compact status and fail when publication or delivery is durably stuck."""
    now = utcnow()
    with db.session_scope() as session:
        counts = status_counts(session)
        edition_counts = counts["editions"]
        delivery_counts = counts["deliveries"]
        subscriptions = session.execute(
            select(func.count()).select_from(DigestSubscription).where(DigestSubscription.active.is_(True))
        ).scalar_one()
        latest_event = session.execute(select(func.max(ToolActivityEvent.event_at))).scalar_one()
        old_validated = session.execute(
            select(func.count())
            .select_from(DigestEdition)
            .where(DigestEdition.status == "validated", DigestEdition.created_at < now - MAX_VALIDATED_AGE)
        ).scalar_one()
        old_outbox = session.execute(
            select(func.count())
            .select_from(DigestDelivery)
            .where(
                DigestDelivery.status.in_(("pending", "retry")),
                DigestDelivery.created_at < now - MAX_OUTBOX_AGE,
            )
        ).scalar_one()
        archive_state = session.get(DigestOperationalState, ARCHIVE_STATE_KEY)
        recent_fallbacks = session.execute(
            select(func.count())
            .select_from(DigestEdition)
            .where(
                DigestEdition.used_fallback.is_(True),
                DigestEdition.created_at >= now - FALLBACK_ALERT_WINDOW,
                # Retiring a backfilled edition leaves its generation history behind.
                # Those rows never reach a reader, so their fallback says nothing about
                # whether Lift Wing is serving the editions that do.
                DigestEdition.status != OUT_OF_SCOPE_STATUS,
            )
        ).scalar_one()
    late_due = [period for period in due_periods(now=now) if period.end <= now - MAX_DUE_PERIOD_AGE]
    problems = []
    if edition_counts.get(PUBLICATION_FAILED_STATUS, 0):
        problems.append("one or more Meta publications failed")
    if old_validated:
        problems.append("validated editions have remained unpublished for over two hours")
    if old_outbox:
        problems.append("delivery outbox rows have remained pending for over 48 hours")
    if delivery_counts.get("failed", 0):
        problems.append("one or more deliveries exhausted transient retries")
    if archive_state is not None and archive_state.last_error:
        problems.append(f"Meta archive refresh failed: {archive_state.last_error}")
    if late_due:
        labels = ", ".join(f"{period.cadence}:{period.key}" for period in late_due[:10])
        problems.append(f"closed digest periods remain ungenerated: {labels}")
    problems.extend(
        _liftwing_problems(has_activity=bool(edition_counts or late_due), recent_fallbacks=recent_fallbacks)
    )
    status: dict[str, object] = {
        "healthy": not problems,
        "problems": problems,
        "editions": edition_counts,
        "deliveries": delivery_counts,
        "activeSubscriptions": subscriptions,
        "latestActivityEvent": latest_event.isoformat() + "Z" if latest_event else None,
        "lateDuePeriods": len(late_due),
        "recentFallbacks": recent_fallbacks,
        # Reported, never alarmed on. Meta will refuse these editions on every future
        # attempt, so an hourly alert would fire forever without any action clearing
        # it; the count keeps them visible for the one-off decision they do need.
        "blockedPublications": edition_counts.get(PUBLICATION_BLOCKED_STATUS, 0),
    }
    if problems:
        raise DigestAuditError("; ".join(problems))
    return status


def main() -> int:
    return job_runner.run_job("digest-audit", audit, lock=True)


if __name__ == "__main__":  # pragma: no cover - Toolforge entrypoint
    raise SystemExit(main())
