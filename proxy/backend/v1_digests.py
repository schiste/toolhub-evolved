# SPDX-License-Identifier: GPL-3.0-or-later
"""Public digest archive, RSS, and authenticated subscription endpoints."""

from __future__ import annotations

from datetime import UTC
from email.utils import format_datetime
from xml.sax.saxutils import escape, quoteattr

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select

from backend import db
from backend.digest_delivery import public_base_url, read_subscription_token, send_confirmation
from backend.digest_health import status_counts
from backend.digests import CADENCES, DEFAULT_LANGUAGE, LIFTWING_AUTHOR, WEBSITE_VISIBLE_STATUSES
from backend.models import (
    DigestEdition,
    DigestEditionTool,
    DigestSubscription,
    User,
    utcnow,
)
from backend.public_identity import WikimediaIdentityProvider
from backend.security import current_user_id, login_required, write_guard
from backend.sync import clean_error
from backend.wikimedia_delivery import WikimediaAPIError, WikimediaClient, clean_wiki_domain

v1_digests_bp = Blueprint("v1_digests", __name__)
CHANNELS = {"email", "talk"}
MAX_FEED_EDITIONS = 50
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_BAD_GATEWAY = 502


def _iso(value: object) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


def _tool_payload(row: DigestEditionTool) -> dict[str, object]:
    return {
        "name": row.tool_name,
        "position": row.position,
        "highlighted": row.highlighted,
        "facts": row.facts,
        "blurb": row.blurb,
    }


def _edition_base_payload(edition: DigestEdition) -> dict[str, object]:
    """Return fields shared by archive summaries and full edition responses."""
    return {
        "cadence": edition.cadence,
        "editionKey": edition.edition_key,
        "language": edition.language_code,
        "periodStart": _iso(edition.period_start),
        "periodEnd": _iso(edition.period_end),
        "title": edition.title,
        "introduction": edition.introduction,
        "publishedAt": _iso(edition.published_at),
        "author": LIFTWING_AUTHOR if not edition.used_fallback else "Toolhub Evolved",
    }


def _edition_payload(edition: DigestEdition, tools: list[DigestEditionTool]) -> dict[str, object]:
    return {
        **_edition_base_payload(edition),
        "html": edition.rendered_html,
        "metaPageTitle": edition.meta_page_title,
        "metaPageUrl": edition.meta_page_url,
        "modelName": edition.model_name,
        "tools": [_tool_payload(row) for row in tools],
    }


def _edition_summary_payload(edition: DigestEdition, tool_count: int) -> dict[str, object]:
    """Return only the fields needed to render one archive row."""
    return {**_edition_base_payload(edition), "toolCount": tool_count}


def _visible_editions(
    cadence: str | None = None,
    *,
    limit: int = MAX_FEED_EDITIONS,
    offset: int = 0,
    statuses: tuple[str, ...] = WEBSITE_VISIBLE_STATUSES,
) -> list[DigestEdition]:
    with db.session_scope() as session:
        statement = select(DigestEdition).where(
            DigestEdition.status.in_(statuses),
            DigestEdition.language_code == DEFAULT_LANGUAGE,
        )
        if cadence:
            statement = statement.where(DigestEdition.cadence == cadence)
        return list(
            session.execute(
                statement.order_by(DigestEdition.period_end.desc(), DigestEdition.id.desc()).offset(offset).limit(limit)
            ).scalars()
        )


def _edition_tool_counts(editions: list[DigestEdition]) -> dict[int, int]:
    """Count one page's frozen tools without loading their large fact snapshots."""
    edition_ids = [edition.id for edition in editions]
    if not edition_ids:
        return {}
    with db.session_scope() as session:
        rows = session.execute(
            select(DigestEditionTool.edition_id, func.count())
            .where(DigestEditionTool.edition_id.in_(edition_ids))
            .group_by(DigestEditionTool.edition_id)
        ).all()
    return {edition_id: int(count) for edition_id, count in rows}


@v1_digests_bp.route("/v1/digests/")
def digest_archive() -> Response:
    """Return the newest immutable published editions from the local database."""
    cadence = request.args.get("cadence", "").strip().casefold() or None
    if cadence is not None and cadence not in CADENCES:
        return jsonify({"error": "cadence must be daily, weekly, or monthly"}), HTTP_BAD_REQUEST
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), MAX_FEED_EDITIONS))
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        return jsonify({"error": "limit and page must be integers"}), HTTP_BAD_REQUEST
    editions = _visible_editions(cadence, limit=limit, offset=(page - 1) * limit)
    tool_counts = _edition_tool_counts(editions)
    with db.session_scope() as session:
        total_statement = (
            select(func.count())
            .select_from(DigestEdition)
            .where(
                DigestEdition.status.in_(WEBSITE_VISIBLE_STATUSES),
                DigestEdition.language_code == DEFAULT_LANGUAGE,
            )
        )
        if cadence:
            total_statement = total_statement.where(DigestEdition.cadence == cadence)
        total = session.execute(total_statement).scalar_one()
    payload = [_edition_summary_payload(edition, tool_counts.get(edition.id, 0)) for edition in editions]
    return jsonify(
        {
            "editions": payload,
            "cadences": list(CADENCES),
            "language": DEFAULT_LANGUAGE,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "hasMore": page * limit < total,
            },
        }
    )


@v1_digests_bp.route("/v1/digests/<cadence>/<edition_key>/")
def digest_detail(cadence: str, edition_key: str) -> Response:
    """Return one published edition by its stable cadence and UTC period key."""
    with db.session_scope() as session:
        edition = session.execute(
            select(DigestEdition).where(
                DigestEdition.cadence == cadence,
                DigestEdition.edition_key == edition_key,
                DigestEdition.language_code == DEFAULT_LANGUAGE,
                DigestEdition.status.in_(WEBSITE_VISIBLE_STATUSES),
            )
        ).scalar_one_or_none()
        if edition is None:
            return jsonify({"error": "digest edition not found"}), HTTP_NOT_FOUND
        tools = list(
            session.execute(
                select(DigestEditionTool)
                .where(DigestEditionTool.edition_id == edition.id)
                .order_by(DigestEditionTool.position, DigestEditionTool.id)
            ).scalars()
        )
        return jsonify(_edition_payload(edition, tools))


def _feed_url(cadence: str) -> str:
    return f"{public_base_url()}/feeds/digests/{cadence}.xml"


@v1_digests_bp.route("/feeds/digests/<cadence>.xml")
def digest_feed(cadence: str) -> Response:
    """Serve a full-content RSS 2.0 feed for one digest cadence."""
    if cadence not in CADENCES:
        return Response("Digest feed not found\n", status=HTTP_NOT_FOUND, content_type="text/plain; charset=utf-8")
    editions = _visible_editions(cadence, statuses=("published",))
    base = public_base_url()
    items: list[str] = []
    for edition in editions:
        local_url = f"{base}/digests/{edition.cadence}/{edition.edition_key}"
        canonical_url = edition.meta_page_url or local_url
        published = (
            format_datetime(edition.published_at.replace(tzinfo=UTC), usegmt=True) if edition.published_at else ""
        )
        items.append(
            "<item>"
            f"<title>{escape(edition.title)}</title>"
            f"<link>{escape(canonical_url)}</link>"
            f"<guid isPermaLink={quoteattr('false')}>{escape(local_url)}</guid>"
            f"<pubDate>{escape(published)}</pubDate>"
            f"<description>{escape(edition.introduction)}</description>"
            f"<content:encoded><![CDATA[{edition.rendered_html.replace(']]>', ']]&gt;')}]]></content:encoded>"
            "</item>"
        )
    latest = editions[0].published_at if editions and editions[0].published_at else utcnow()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        "<channel>"
        f"<title>Toolhub {escape(cadence.title())} Digest</title>"
        f"<link>{escape(base + '/digests/' + cadence)}</link>"
        "<description>Short editorial updates about newly added Toolhub tools.</description>"
        "<language>en</language>"
        f"<lastBuildDate>{escape(format_datetime(latest.replace(tzinfo=UTC), usegmt=True))}</lastBuildDate>"
        '<atom:link xmlns:atom="http://www.w3.org/2005/Atom" '
        f'href={quoteattr(_feed_url(cadence))} rel="self" type="application/rss+xml"/>'
        f"{''.join(items)}</channel></rss>"
    )
    return Response(
        xml,
        content_type="application/rss+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _subscription_payload(row: DigestSubscription) -> dict[str, object]:
    return {
        "id": row.id,
        "channel": row.channel,
        "cadence": row.cadence,
        "language": row.language_code,
        "wikiDomain": row.wiki_domain,
        "wikiUsername": row.wiki_username,
        "active": row.active,
        "confirmed": row.confirmed_at is not None,
        "createdAt": _iso(row.created_at),
        "lastError": row.last_error,
    }


@v1_digests_bp.route("/v1/digests/subscriptions/", methods=["GET"])
@login_required
def subscriptions_get() -> Response:
    uid = current_user_id()
    with db.session_scope() as session:
        rows = list(
            session.execute(
                select(DigestSubscription)
                .where(DigestSubscription.user_id == uid)
                .order_by(DigestSubscription.created_at, DigestSubscription.id)
            ).scalars()
        )
        return jsonify({"subscriptions": [_subscription_payload(row) for row in rows]})


def _request_subscription() -> tuple[str, str, str, str]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        message = "a JSON object is required"
        raise TypeError(message)
    channel = str(body.get("channel") or "").strip().casefold()
    cadence = str(body.get("cadence") or "").strip().casefold()
    language = str(body.get("language") or DEFAULT_LANGUAGE).strip().casefold()
    if channel not in CHANNELS:
        message = "channel must be email or talk"
        raise ValueError(message)
    if cadence not in CADENCES:
        message = "cadence must be daily, weekly, or monthly"
        raise ValueError(message)
    if language != DEFAULT_LANGUAGE:
        message = "only English subscriptions are available right now"
        raise ValueError(message)
    domain = "meta.wikimedia.org" if channel == "email" else clean_wiki_domain(str(body.get("wikiDomain") or ""))
    return channel, cadence, language, domain


@v1_digests_bp.route("/v1/digests/subscriptions/", methods=["POST"])
@write_guard
def subscriptions_post() -> Response:  # noqa: PLR0911 - each upstream/identity failure has a distinct API response
    try:
        channel, cadence, language, domain = _request_subscription()
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), HTTP_BAD_REQUEST
    uid = current_user_id()
    with db.session_scope() as session:
        user = session.get(User, uid)
        global_id = user.wikimedia_global_user_id if user is not None else None
    if not global_id:
        return jsonify({"error": "connect a Wikimedia account before subscribing"}), HTTP_BAD_REQUEST
    identity = WikimediaIdentityProvider().lookup(global_id)
    if identity is None:
        return jsonify({"error": "the connected Wikimedia identity could not be verified"}), HTTP_BAD_GATEWAY
    wiki = WikimediaClient()
    try:
        if not wiki.user_identity_matches(domain, identity.username, global_id):
            return jsonify({"error": f"{identity.username} does not have an account on {domain}"}), HTTP_BAD_REQUEST
    except WikimediaAPIError as exc:
        return jsonify({"error": clean_error(str(exc)), "code": exc.code}), HTTP_BAD_GATEWAY
    now = utcnow()
    with db.session_scope() as session:
        subscription = session.execute(
            select(DigestSubscription).where(
                DigestSubscription.user_id == uid,
                DigestSubscription.channel == channel,
                DigestSubscription.cadence == cadence,
                DigestSubscription.wiki_domain == domain,
                DigestSubscription.language_code == language,
            )
        ).scalar_one_or_none()
        if subscription is None:
            subscription = DigestSubscription(
                user_id=uid,
                channel=channel,
                cadence=cadence,
                language_code=language,
                wiki_domain=domain,
            )
            session.add(subscription)
        subscription.wiki_username = identity.username
        subscription.updated_at = now
        subscription.last_error = None
        subscription.confirmed_at = now if channel == "talk" else None
        subscription.active = channel == "talk"
        session.flush()
        subscription_id = subscription.id
        payload = _subscription_payload(subscription)
    if channel == "email":
        try:
            send_confirmation(subscription_id, client=wiki)
        except (OSError, RuntimeError, ValueError, WikimediaAPIError) as exc:
            with db.session_scope() as session:
                stored = session.get(DigestSubscription, subscription_id)
                if stored is not None:
                    stored.last_error = clean_error(str(exc))
            return (
                jsonify({"error": "the confirmation email could not be sent", "subscription": payload}),
                HTTP_BAD_GATEWAY,
            )
    return jsonify({"subscription": payload}), 201


def _apply_token(action: str) -> Response:
    body = request.get_json(silent=True)
    token = str(body.get("token") or "") if isinstance(body, dict) else ""
    try:
        subscription_id, user_id = read_subscription_token(token, action)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTP_BAD_REQUEST
    with db.session_scope() as session:
        row = session.get(DigestSubscription, subscription_id)
        if row is None or row.user_id != user_id:
            return jsonify({"error": "subscription not found"}), HTTP_NOT_FOUND
        if action == "confirm":
            row.active = True
            row.confirmed_at = row.confirmed_at or utcnow()
            row.last_error = None
        else:
            row.active = False
        row.updated_at = utcnow()
        return jsonify({"subscription": _subscription_payload(row)})


@v1_digests_bp.route("/v1/digests/subscriptions/confirm/", methods=["POST"])
def subscriptions_confirm() -> Response:
    return _apply_token("confirm")


@v1_digests_bp.route("/v1/digests/subscriptions/unsubscribe/", methods=["POST"])
def subscriptions_unsubscribe() -> Response:
    return _apply_token("unsubscribe")


@v1_digests_bp.route("/v1/digests/subscriptions/<int:subscription_id>/", methods=["DELETE"])
@write_guard
def subscriptions_delete(subscription_id: int) -> Response:
    uid = current_user_id()
    with db.session_scope() as session:
        row = session.get(DigestSubscription, subscription_id)
        if row is None or row.user_id != uid:
            return jsonify({"error": "subscription not found"}), HTTP_NOT_FOUND
        row.active = False
        row.updated_at = utcnow()
        return jsonify({"subscription": _subscription_payload(row)})


@v1_digests_bp.route("/v1/digests/status/")
@login_required
def digest_status() -> Response:
    """Return bounded operational counts for signed-in maintainers and diagnostics."""
    with db.session_scope() as session:
        return jsonify(status_counts(session))
