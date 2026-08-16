# SPDX-License-Identifier: GPL-3.0-or-later
"""Digest subscription confirmation and restart-safe push delivery outbox."""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from backend import db
from backend.digests import edition_marker, public_base_url, wiki_plaintext
from backend.models import DigestDelivery, DigestEdition, DigestSubscription, User, utcnow
from backend.public_identity import WikimediaIdentity, WikimediaIdentityProvider
from backend.sync import clean_error
from backend.wikimedia_delivery import WikimediaAPIError, WikimediaClient

CONFIRMATION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_ATTEMPTS = 8
MAX_RETRY_HOURS = 24


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("DIGEST_SIGNING_SECRET") or os.environ.get("TOOLHUB_SECRET_KEY")
    if not secret:
        message = "DIGEST_SIGNING_SECRET or TOOLHUB_SECRET_KEY is required"
        raise RuntimeError(message)
    return URLSafeTimedSerializer(secret, salt="toolhub-digest-subscriptions-v1")


def subscription_token(subscription_id: int, user_id: int, action: str) -> str:
    """Sign a confirmation or unsubscribe token without exposing user data."""
    return _serializer().dumps({"subscription_id": subscription_id, "user_id": user_id, "action": action})


def read_subscription_token(token: str, action: str) -> tuple[int, int]:
    """Validate a short-lived confirmation or lifetime unsubscribe token."""
    try:
        max_age = CONFIRMATION_MAX_AGE_SECONDS if action == "confirm" else None
        payload = _serializer().loads(token, max_age=max_age)
    except SignatureExpired as exc:
        message = "subscription link expired"
        raise ValueError(message) from exc
    except BadSignature as exc:
        message = "subscription link is invalid"
        raise ValueError(message) from exc
    if not isinstance(payload, dict) or payload.get("action") != action:
        message = "subscription link action is invalid"
        raise ValueError(message)
    try:
        return int(payload["subscription_id"]), int(payload["user_id"])
    except (KeyError, TypeError, ValueError) as exc:
        message = "subscription link payload is invalid"
        raise ValueError(message) from exc


def unsubscribe_url(subscription: DigestSubscription) -> str:
    """Return the signed one-click unsubscribe URL for a subscription."""
    token = subscription_token(subscription.id, subscription.user_id, "unsubscribe")
    return f"{public_base_url()}/digests/unsubscribe?token={token}"


def _queue_deliveries_once(edition_id: int) -> int:
    created = 0
    with db.session_scope() as session:
        edition = session.get(DigestEdition, edition_id)
        if edition is None or edition.status != "published":
            return 0
        subscriptions = list(
            session.execute(
                select(DigestSubscription).where(
                    DigestSubscription.active.is_(True),
                    DigestSubscription.confirmed_at.is_not(None),
                    DigestSubscription.cadence == edition.cadence,
                    DigestSubscription.language_code == edition.language_code,
                    DigestSubscription.confirmed_at <= edition.published_at,
                )
            ).scalars()
        )
        existing = set(
            session.execute(
                select(DigestDelivery.subscription_id).where(DigestDelivery.edition_id == edition_id)
            ).scalars()
        )
        for subscription in subscriptions:
            if subscription.id in existing:
                continue
            session.add(DigestDelivery(edition_id=edition_id, subscription_id=subscription.id))
            created += 1
    return created


def queue_deliveries(edition_id: int) -> int:
    """Create missing outbox rows, recovering from a concurrent repair pass."""
    try:
        return _queue_deliveries_once(edition_id)
    except IntegrityError:
        return _queue_deliveries_once(edition_id)


def queue_published_editions() -> int:
    """Backfill delivery rows for every published edition and current subscription."""
    with db.session_scope() as session:
        edition_ids = list(
            session.execute(select(DigestEdition.id).where(DigestEdition.status == "published")).scalars()
        )
    return sum(queue_deliveries(edition_id) for edition_id in edition_ids)


def _deliver(
    edition: DigestEdition,
    subscription: DigestSubscription,
    client: WikimediaClient,
) -> str:
    if subscription.channel == "email":
        body = (
            f"{edition.rendered_text}\n\nCanonical edition: {edition.meta_page_url}"
            f"\n\nUnsubscribe: {unsubscribe_url(subscription)}"
        )
        return client.email_user(
            "meta.wikimedia.org",
            subscription.wiki_username,
            edition.title,
            body,
        )
    if subscription.channel == "talk":
        marker = edition_marker(edition)
        body = (
            f"{marker}\n{wiki_plaintext(edition.introduction)}\n\n"
            f"'''[{edition.meta_page_url} Read the complete digest on Meta-Wiki].'''\n\n"
            f"<small>Manage this subscription at {public_base_url()}/digests.</small>"
        )
        result = client.append_talk_section(
            subscription.wiki_domain,
            subscription.wiki_username,
            edition.title,
            body,
            marker,
        )
        return result.revision_id
    message = f"unsupported digest delivery channel: {subscription.channel}"
    raise ValueError(message)


def _current_identity(
    subscription_id: int,
    client: WikimediaClient,
    provider: WikimediaIdentityProvider,
    cache: dict[str, WikimediaIdentity],
) -> DigestSubscription:
    """Refresh a rename-safe delivery target and verify its local attachment."""
    with db.session_scope() as session:
        subscription = session.get(DigestSubscription, subscription_id)
        user = session.get(User, subscription.user_id) if subscription is not None else None
        global_id = str(user.wikimedia_global_user_id or "") if user is not None else ""
        domain = subscription.wiki_domain if subscription is not None else ""
    if subscription is None or not global_id:
        message = "subscription has no connected Wikimedia identity"
        raise ValueError(message)
    identity = cache.get(global_id)
    if identity is None:
        identity = provider.lookup(global_id)
        if identity is None:
            message = "connected Wikimedia identity could not be resolved"
            raise RuntimeError(message)
        cache[global_id] = identity
    if not client.user_identity_matches(domain, identity.username, global_id):
        message = f"{identity.username} is not attached to {domain} with the expected CentralAuth identity"
        code = "identity-mismatch"
        raise WikimediaAPIError(code, message, permanent=True, recipient_failure=True)
    with db.session_scope() as session:
        refreshed = session.get(DigestSubscription, subscription_id)
        if refreshed is None:
            message = "digest subscription disappeared during delivery"
            raise ValueError(message)
        refreshed.wiki_username = identity.username
        refreshed.updated_at = utcnow()
        session.flush()
        return refreshed


def _record_failure(delivery_id: int, subscription_id: int, exc: Exception, now: datetime) -> str:
    """Persist one delivery failure and return its stable outcome label."""
    recipient_failure = isinstance(exc, WikimediaAPIError) and exc.recipient_failure
    with db.session_scope() as session:
        failed = session.get(DigestDelivery, delivery_id)
        subscription = session.get(DigestSubscription, subscription_id)
        if failed is None:
            return "skipped"
        failed.attempts += 1
        failed.last_error = clean_error(str(exc))
        if recipient_failure:
            failed.status = "suspended"
            if subscription is not None:
                subscription.active = False
                subscription.last_error = failed.last_error
            session.execute(
                update(DigestDelivery)
                .where(
                    DigestDelivery.subscription_id == subscription_id,
                    DigestDelivery.id != delivery_id,
                    DigestDelivery.status.in_(("pending", "retry")),
                )
                .values(status="cancelled", last_error="subscription disabled after permanent failure")
            )
            return "suspended"
        if failed.attempts >= MAX_ATTEMPTS:
            failed.status = "failed"
            return "failed"
        failed.status = "retry"
        delay_hours = min(MAX_RETRY_HOURS, 2 ** max(0, failed.attempts - 1))
        failed.next_attempt_at = now + timedelta(hours=delay_hours)
        return "retry"


def _deliver_one(
    delivery_id: int,
    wiki: WikimediaClient,
    provider: WikimediaIdentityProvider,
    identity_cache: dict[str, WikimediaIdentity],
    now: datetime,
) -> str:
    """Process one outbox row and return a counter-safe outcome label."""
    with db.session_scope() as session:
        delivery = session.get(DigestDelivery, delivery_id)
        edition = session.get(DigestEdition, delivery.edition_id) if delivery is not None else None
        subscription = session.get(DigestSubscription, delivery.subscription_id) if delivery is not None else None
    if delivery is None or edition is None or subscription is None:
        return "skipped"
    if not subscription.active:
        with db.session_scope() as session:
            stale = session.get(DigestDelivery, delivery_id)
            if stale is not None:  # pragma: no branch - delete-mid-cancellation operator race
                stale.status = "cancelled"
        return "cancelled"
    try:
        subscription = _current_identity(subscription.id, wiki, provider, identity_cache)
        external_id = _deliver(edition, subscription, wiki)
    except (OSError, RuntimeError, ValueError, WikimediaAPIError) as exc:
        return _record_failure(delivery_id, subscription.id, exc, now)
    with db.session_scope() as session:
        completed = session.get(DigestDelivery, delivery_id)
        stored_subscription = session.get(DigestSubscription, subscription.id)
        if completed is not None:
            completed.status = "delivered"
            completed.attempts += 1
            completed.external_id = external_id
            completed.delivered_at = utcnow()
            completed.last_error = None
        if stored_subscription is not None:
            stored_subscription.last_error = None
    return "delivered"


def deliver_pending(
    *,
    limit: int = 100,
    client: WikimediaClient | None = None,
    identity_provider: WikimediaIdentityProvider | None = None,
) -> dict[str, int]:
    """Drain a bounded delivery batch with exponential retries and permanent suspension."""
    now = utcnow()
    with db.session_scope() as session:
        delivery_ids = list(
            session.execute(
                select(DigestDelivery.id)
                .where(
                    DigestDelivery.status.in_(("pending", "retry")),
                    DigestDelivery.next_attempt_at <= now,
                )
                .order_by(DigestDelivery.next_attempt_at, DigestDelivery.id)
                .limit(max(1, min(limit, 500)))
            ).scalars()
        )
    wiki = client or WikimediaClient()
    provider = identity_provider or WikimediaIdentityProvider()
    identity_cache: dict[str, WikimediaIdentity] = {}
    outcomes: Counter[str] = Counter()
    for delivery_id in delivery_ids:
        outcomes[_deliver_one(delivery_id, wiki, provider, identity_cache, now)] += 1
    return {key: outcomes[key] for key in ("delivered", "retry", "suspended", "failed", "cancelled", "skipped")}
