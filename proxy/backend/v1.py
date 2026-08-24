# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1 JSON API: session info + the synced overlay, plus public feeds.

The SPA keeps using localStorage as its synchronous overlay cache; when a real
session exists it pulls GET /v1/overlay/ into that cache and pushes every
mutation back with PUT /v1/overlay/<key> (write-through). Payload shapes are
therefore exactly the shapes the SPA already stores (lib/core/store.js).

Per-user keys (favorites, lists, crawlerUrls) use replace semantics. Overlay
keys (toolEdits, toolAnnos, toolNew) replace only the calling user's rows; the
assembled GET merges all users' rows, newest first. Feed keys (revisions,
auditlogs) are append-only, idempotent by client id.
"""

import json
import os
import re
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from urllib.parse import quote, unquote, urlencode
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import select, text

from backend import (
    activity_privacy,
    authz,
    canonical_tools,
    catalog_read,
    db,
    github_issues,
    graph_payload,
    home_payload,
    recent_owners,
    security,
    tool_summaries,
)
from backend import v1_common as common
from backend.author_claims import (
    AuthorNameProvider,
    SignedToolinfoProvider,
    ToolforgeMaintainerProvider,
)
from backend.models import (
    CatalogCuration,
    IssueReport,
    ToolHealthTarget,
    ToolMedia,
    ToolRecord,
    ToolThanks,
    User,
    utcnow,
)
from backend.oauth import configured as oauth_configured
from backend.oauth import dev_login_available
from backend.public_identity import PublicIdentityResolver
from backend.security import current_user_id, login_required, write_guard
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    REVIEW_APPROVED,
    REVIEW_OPEN,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
    clean_error,
    clean_int,
)

v1_bp = Blueprint("v1", __name__)

HTTP_NO_CONTENT = 204
HTTP_TOO_MANY = 429
MAX_ITEMS = 500  # per overlay key per user
FEED_KEEP_CAP = 500
RSS_FEED_PAGE_SIZE = 30
RSS_CONTENT_TYPE = "application/rss+xml; charset=utf-8"
# Last-resort base URL for links inside publicly cached responses when
# TOOLHUB_EVOLVED_BASE_URL is unset. A constant, never the request Host — see
# _public_base_url for why that distinction is the whole point.
DEFAULT_PUBLIC_BASE_URL = "https://toolhub-evolved.toolforge.org"
ME_TOOLS_SEARCH_PAGE_SIZE = 100
ME_TOOLS_MAX_SEARCH_TERMS = 20
SIGNATURE_PLACEHOLDER = "<base64 signature>"
EVENT_TYPES = {"view", "launch", "save", "list_add"}
CLAIM_METHODS = {
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
}
MODERATION_MODELS = {
    "catalog-curations": CatalogCuration,
    "tool-records": ToolRecord,
    "health-targets": ToolHealthTarget,
    "media": ToolMedia,
    "thanks": ToolThanks,
}
PUBLIC_REVIEW_STATUSES = {REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED}
MODERATION_KINDS = set(MODERATION_MODELS)
TOOL_FALLBACK_KINDS = {"new", "edit", "annotations"}
TOOL_OVERLAY_KIND_BY_FALLBACK = {"edit": "edits", "annotations": "annos"}
OFFICIAL_STATUS_DISCARDED = "discarded"
AUTHOR_NAME_PROVIDER = AuthorNameProvider()
SIGNED_TOOLINFO_PROVIDER = SignedToolinfoProvider()
TOOLFORGE_MAINTAINER_PROVIDER = ToolforgeMaintainerProvider()
PUBLIC_IDENTITY_RESOLVER = PublicIdentityResolver()
TOOLINFO_CREATE_MAX_ITEMS = 200
TOOLINFO_CREATE_OPT_FIELDS = ("repository", "license", "toolType")
TOOLINFO_CREATE_LIST_FIELDS = ("keywords", "forWikis", "uiLanguages")
TOOLINFO_CREATE_BOOL_FIELDS = ("deprecated", "experimental")
SOURCE_ANALYSIS_REVIEW_STATUSES = {REVIEW_OPEN, REVIEW_APPROVED, REVIEW_REJECTED}
SOURCE_ANALYSIS_DEFAULT_LIMIT = 20
SOURCE_ANALYSIS_MAX_LIMIT = 50
SOURCE_ANALYSIS_NOT_FOUND = "source analysis report not found"
TOOL_SUMMARY_DEFAULT_LIMIT = 24


def _public_base_url() -> str:
    """Return the canonical base URL for links embedded in publicly cached output.

    request.url_root is built from the Host header, which the client controls.
    The feeds that consume this are served `Cache-Control: public, max-age=300`,
    so deriving the base URL from a request would let one forged Host put
    attacker-chosen <link>/<guid> values into a shared cache and serve them to
    everyone else for five minutes.

    Production therefore takes the value from configuration only, exactly like
    the OAuth callback (backend.oauth._callback_url) already does for the same
    reason. The fallback is a constant, not a header: an unset variable degrades
    to the wrong-but-fixed canonical host rather than to whatever was asked for.
    Header derivation stays available under the local-development flag, where
    there is no shared cache and no registered hostname to protect.
    """
    configured = os.environ.get("TOOLHUB_EVOLVED_BASE_URL", "").rstrip("/")
    if configured:
        return configured
    if os.environ.get("TOOLHUB_INSECURE_COOKIES") == "1":
        return request.url_root.rstrip("/")
    return DEFAULT_PUBLIC_BASE_URL


def _site_url(path: str) -> str:
    return f"{_public_base_url()}{path if path.startswith('/') else '/' + path}"


def _feed_text(value: Any, fallback: str = "") -> str:  # noqa: ANN401 - Toolhub payloads are heterogeneous JSON
    if isinstance(value, dict):
        for key in ("en", "mul"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
        for candidate in value.values():
            if candidate:
                return str(candidate)
        return fallback
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item) or fallback
    text_value = str(value or "").strip()
    return text_value or fallback


def _rss_date(value: Any) -> str:  # noqa: ANN401 - accepts ISO strings and datetime values
    dt = value if isinstance(value, datetime) else common.parse_optional_iso(value)
    if dt is None:
        dt = utcnow()
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return format_datetime(dt, usegmt=True)


def _rss_item(title: str, link: str, description: str, published: Any, guid: str) -> dict[str, str]:  # noqa: ANN401
    return {
        "title": title,
        "link": link,
        "description": description,
        "pubDate": _rss_date(published),
        "guid": guid,
    }


def _rss_xml(title: str, description: str, link: str, items: list[dict[str, str]]) -> str:
    item_xml = "\n".join(
        f"""		<item>
			<title>{xml_escape(item["title"])}</title>
			<link>{xml_escape(item["link"])}</link>
			<guid isPermaLink="false">{xml_escape(item["guid"])}</guid>
			<pubDate>{xml_escape(item["pubDate"])}</pubDate>
			<description>{xml_escape(item["description"])}</description>
		</item>"""
        for item in items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
	<channel>
		<title>{xml_escape(title)}</title>
		<link>{xml_escape(link)}</link>
		<description>{xml_escape(description)}</description>
		<language>en</language>
		<lastBuildDate>{xml_escape(_rss_date(utcnow()))}</lastBuildDate>
{item_xml}
	</channel>
</rss>
"""


def _rss_response(title: str, description: str, link_path: str, items: list[dict[str, str]]) -> Response:
    resp = Response(_rss_xml(title, description, _site_url(link_path), items), content_type=RSS_CONTENT_TYPE)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def _feed_payload(path: str, params: dict[str, object] | None = None) -> list[dict[str, Any]]:
    if path.rstrip("/") == "/api/recent":
        payload = catalog_read.collection_payload("/api/recent/", params or {})
    elif path.rstrip("/") == "/api/lists":
        payload = catalog_read.collection_payload("/api/lists/", params or {})
    elif path.rstrip("/") == "/api/search/tools":
        payload = catalog_read.search_payload(params or {})
    else:
        query = urlencode(params or {})
        cached = catalog_read.cached_payload(f"https://toolhub.wikimedia.org{path}{('?' + query) if query else ''}")
        payload = json.loads(cached[0].decode("utf-8")) if cached is not None else {}
    if not isinstance(payload, dict):
        return []
    rows = payload.get("results")
    public_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return activity_privacy.public_activity_rows(public_rows) if path.rstrip("/") == "/api/recent" else public_rows


def _upstream_feed_error(exc: Exception) -> Response:
    resp = jsonify({"error": "feed upstream unavailable", "detail": clean_error(str(exc))})
    resp.status_code = common.HTTP_BAD_GATEWAY
    return resp


def _recent_feed_item(row: dict[str, Any]) -> dict[str, str]:
    content_type = _feed_text(row.get("content_type"), "item")
    content_id = _feed_text(row.get("content_id"))
    title = _feed_text(row.get("content_title"), content_id or "Toolhub item")
    action = "Updated" if row.get("parent_id") else "Created"
    username = _feed_text(row.get("user", {}).get("username") if isinstance(row.get("user"), dict) else "", "system")
    comment = _feed_text(row.get("comment"))
    path = (
        f"/tools/{quote(content_id, safe='')}"
        if content_type == "tool" and content_id
        else f"/lists/{quote(content_id, safe='')}"
        # Upstream reports list revisions as "toollist"; Evolved rows use "list".
        if content_type in {"list", "toollist"} and content_id
        else "/recent"
    )
    detail = f"{action} by {username}."
    if comment:
        detail = f"{detail} {comment}"
    guid = f"toolhub-recent:{row.get('id') or row.get('timestamp') or content_type + ':' + content_id}"
    return _rss_item(f"{action} {content_type}: {title}", _site_url(path), detail, row.get("timestamp"), guid)


def _tool_feed_item(row: dict[str, Any]) -> dict[str, str]:
    name = _feed_text(row.get("name"))
    title = _feed_text(row.get("title"), name or "Toolhub tool")
    description = _feed_text(row.get("description"), f"Toolhub tool {name or title}.")
    modified = row.get("modified_date") or row.get("modified")
    link = _site_url(f"/tools/{quote(name, safe='')}") if name else _site_url("/search")
    guid = f"toolhub-tool:{name or title}"
    return _rss_item(title, link, description, modified, guid)


def _list_feed_item(row: dict[str, Any]) -> dict[str, str]:
    list_id = _feed_text(row.get("id"))
    title = _feed_text(row.get("title"), f"Toolhub list {list_id}")
    description = _feed_text(row.get("description"), f"Toolhub list {title}.")
    modified = row.get("modified_date") or row.get("modified") or row.get("created_date") or row.get("created")
    link = _site_url(f"/lists/{quote(list_id, safe='')}") if list_id else _site_url("/lists")
    return _rss_item(title, link, description, modified, f"toolhub-list:{list_id or title}")


def _revision_feed_item(row: dict[str, Any], *, label: str, history_path: str, kind: str) -> dict[str, str]:
    revision_id = _feed_text(row.get("id"), _feed_text(row.get("timestamp"), "revision"))
    username = _feed_text(row.get("user", {}).get("username") if isinstance(row.get("user"), dict) else "", "system")
    comment = _feed_text(row.get("comment"))
    description = f"Revision by {username}."
    if comment:
        description = f"{description} {comment}"
    return _rss_item(
        f"Revision {revision_id}: {label}",
        _site_url(history_path),
        description,
        row.get("timestamp"),
        f"toolhub-{kind}-revision:{label}:{revision_id}",
    )


@v1_bp.route("/feeds/recent.xml")
def feed_recent() -> Response:
    """RSS feed for official Toolhub recent changes."""
    try:
        rows = _feed_payload("/api/recent/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        "Toolhub recent changes",
        "Recent official Toolhub catalog activity.",
        "/recent",
        [_recent_feed_item(row) for row in rows],
    )


@v1_bp.route("/feeds/tools/recently-updated.xml")
def feed_recently_updated_tools() -> Response:
    """RSS feed for recently updated tools."""
    try:
        rows = _feed_payload(
            "/api/search/tools/",
            {"ordering": "-modified_date", "page_size": RSS_FEED_PAGE_SIZE},
        )
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        "Toolhub recently updated tools",
        "Tools ordered by the official Toolhub modified date.",
        "/search?sort=recent",
        [_tool_feed_item(row) for row in rows],
    )


@v1_bp.route("/feeds/lists.xml")
def feed_lists() -> Response:
    """RSS feed for public Toolhub lists."""
    try:
        rows = _feed_payload("/api/lists/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        "Toolhub lists",
        "Recently visible public Toolhub lists.",
        "/lists",
        [_list_feed_item(row) for row in rows],
    )


@v1_bp.route("/feeds/tools/<path:name>/revisions.xml")
def feed_tool_revisions(name: str) -> Response:
    """RSS feed for one tool's official revision history."""
    clean_name = common.clean_name(unquote(name))
    if clean_name is None:
        return common.bad("tool name is required")
    try:
        rows = _feed_payload(f"/api/tools/{quote(clean_name, safe='')}/revisions/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        f"Toolhub revisions: {clean_name}",
        f"Official Toolhub revision history for {clean_name}.",
        f"/tools/{quote(clean_name, safe='')}/history",
        [
            _revision_feed_item(
                row,
                label=clean_name,
                history_path=f"/tools/{quote(clean_name, safe='')}/history",
                kind="tool",
            )
            for row in rows
        ],
    )


@v1_bp.route("/feeds/lists/<list_id>/revisions.xml")
def feed_list_revisions(list_id: str) -> Response:
    """RSS feed for one list's official revision history."""
    clean_id = str(list_id or "").strip()[: common.MAX_NAME]
    if not clean_id:
        return common.bad("list id is required")
    try:
        rows = _feed_payload(f"/api/lists/{quote(clean_id, safe='')}/revisions/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        f"Toolhub list revisions: {clean_id}",
        f"Official Toolhub revision history for list {clean_id}.",
        f"/lists/{quote(clean_id, safe='')}/history",
        [
            _revision_feed_item(
                row,
                label=clean_id,
                history_path=f"/lists/{quote(clean_id, safe='')}/history",
                kind="list",
            )
            for row in rows
        ],
    )


def _public_tool_record_payload(row: ToolRecord) -> dict:
    """Return public tool data without private write diagnostics."""
    out = common.tool_record_payload(row)
    for key in ("lastError", "toolhubResponse", "validationErrors"):
        out.pop(key, None)
    return out


@v1_bp.route("/healthz")
def healthz() -> Response:
    """Liveness + database reachability (used by uptime monitoring)."""
    try:
        with db.session_scope() as s:
            s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — a health probe reports any failure the same way
        resp = jsonify({"ok": False})
        resp.status_code = 503
        return resp
    return jsonify({"ok": True})


#: Matches the client's own per-render cap, so this never composes summaries
#: for tools the page will not draw.


@v1_bp.route("/v1/config/")
def v1_config() -> Response:
    """Report which production capabilities are configured (no secrets)."""
    oauth = oauth_configured()
    return jsonify(
        {
            "oauth": oauth,
            "officialWrites": oauth,
            "devLogin": dev_login_available(),
            "issueReports": github_issues.configured(),
        }
    )


@v1_bp.route("/v1/debug/forwarded/")
@login_required
def v1_debug_forwarded() -> Response:
    """TEMPORARY: report how this request was forwarded, to size ProxyFix.

    Delete this route once the hop count is recorded in backend.register.

    Why it has to exist: the read and write rate limiters key on
    request.remote_addr, and no ProxyFix is installed, so behind the Toolforge
    front proxy every visitor shares one bucket — 121 requests from anyone
    returns 429 to everyone. Fixing that means ProxyFix(x_for=N), and N is the
    one value that cannot be guessed safely: too high and a client forges
    X-Forwarded-For to mint a fresh identity per request (an unlimited bucket,
    strictly worse than today), too low and it degrades back to the shared
    bucket. Only a real request through the real proxy chain answers it.

    `candidates` does the arithmetic: ProxyFix with x_for=N takes the Nth entry
    from the right, so the correct N is whichever row equals the caller's own
    public IP. Signed-in only — this reflects the caller's own request back to
    them, and there is no reason to hand the cluster's forwarding shape to
    anonymous traffic.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    entries = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    return jsonify(
        {
            "remoteAddr": request.remote_addr,
            "xForwardedFor": forwarded_for,
            "xForwardedForEntries": entries,
            "hopCount": len(entries),
            "candidates": {f"x_for={n}": entries[-n] for n in range(1, len(entries) + 1)},
            "accessRoute": list(request.access_route),
            "xForwardedProto": request.headers.get("X-Forwarded-Proto", ""),
            "xRealIp": request.headers.get("X-Real-IP", ""),
            "forwarded": request.headers.get("Forwarded", ""),
            "host": request.host,
        }
    )


@v1_bp.route("/v1/issue-reports/", methods=["POST"])
@write_guard
def v1_issue_report() -> Response:  # noqa: C901, PLR0911 - validation exits keep publication guard explicit
    """Publish an explicitly approved, authenticated report to GitHub."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("approved") is not True:
        return common.bad("explicit issue approval is required")
    client_id = str(payload.get("clientId") or "").strip()
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip()
    context = payload.get("context")
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,64}", client_id):
        return common.bad("invalid issue report id")
    if not title or len(title) > github_issues.MAX_TITLE:
        return common.bad("issue title must be between 1 and 200 characters")
    if not description or len(description) > github_issues.MAX_DESCRIPTION:
        return common.bad("issue description is required and must be at most 12000 characters")
    if not isinstance(context, dict):
        return common.bad("issue context must be an object")
    try:
        context_size = len(json.dumps(context, ensure_ascii=False))
    except (TypeError, ValueError):
        return common.bad("issue context is not valid JSON")
    if context_size > github_issues.MAX_CONTEXT_CHARS:
        return common.bad("issue context is too large")
    with db.session_scope() as s:
        existing = s.get(IssueReport, client_id)
        if existing is not None:
            if existing.user_id != uid:
                return common.deny(common.HTTP_CONFLICT, "issue report id already belongs to another user")
            return jsonify(
                {"number": existing.issue_number, "url": existing.issue_url, "repository": existing.repository}
            )
        user = s.get(User, uid)
        if user is None:
            return common.deny(common.HTTP_UNAUTHORIZED, "signed-in user not found")
        body = github_issues.render_body(description, context, user.username)
        try:
            published = github_issues.publish_issue(title, body)
        except github_issues.IssuePublishError as exc:
            return common.deny(common.HTTP_BAD_GATEWAY, str(exc))
        s.add(
            IssueReport(
                client_id=client_id,
                user_id=uid,
                title=title,
                repository=published["repository"],
                issue_number=published["number"],
                issue_url=published["url"],
            )
        )
    return jsonify(published), 201


@v1_bp.route("/v1/canonical/tools/")
def v1_canonical_tools() -> Response:
    """Return locally cached canonical official Toolhub tool records."""
    names = common.tool_names_from_request()
    q = str(request.args.get("q") or "").strip()
    limit = min(
        max(clean_int(request.args.get("limit")) or TOOL_SUMMARY_DEFAULT_LIMIT, 1), common.TOOL_SUMMARY_MAX_NAMES
    )
    if names:
        rows_by_name = canonical_tools.tools_by_name(names)
        results = [rows_by_name[name] for name in names if name in rows_by_name]
    else:
        results = canonical_tools.search(
            q,
            limit=limit,
            include_archived=catalog_read.include_archived(request.args),
            statuses=catalog_read.selected_statuses(request.args),
        )
    return jsonify(
        {
            "count": len(results),
            "results": results,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "cachePolicy": {
                "canonical": True,
                "upstream": False,
                "summary": "Local structured cache populated from prior official Toolhub API reads.",
            },
        }
    )


@v1_bp.route("/v1/home/")
def v1_home() -> Response:
    """Return the whole landing page in one composed, cached payload.

    The homepage previously needed nine reads with a dependency between them —
    summaries and the most-listed ordering could not start until the list and
    search reads returned. Composing here collapses that into one request.
    """
    return common.public_json_response(
        home_payload.payload(
            lambda names: tool_summaries.summaries_for(
                names, common.build_local_tool_summary, view=tool_summaries.VIEW_CARD
            ),
        )
    )


@v1_bp.route("/v1/graph/")
def v1_graph() -> Response:
    """Return a cached global graph derived from the local canonical catalog."""
    return common.public_json_response(
        graph_payload.payload(
            limit=request.args.get("limit"),
            group_by=request.args.get("groupBy"),
        )
    )


@v1_bp.route("/v1/media/<int:media_id>/", methods=["DELETE"])
@write_guard
def v1_tool_media_delete(media_id: int) -> Response:
    """Soft-delete a media row owned by the caller."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        row = s.get(ToolMedia, media_id)
        if row is None or not authz.can(user, authz.ACTION_PRIVATE_DELETE, row):
            resp = jsonify({"error": "media not found"})
            resp.status_code = common.HTTP_NOT_FOUND
            return resp
        row.deleted_at = utcnow()
    return jsonify({"ok": True})


@v1_bp.route("/v1/search/tools/")
def v1_search() -> Response:
    """Search locally-registered tools (public).

    Federated with live search client-side; upstream results always come
    straight from the Toolhub API.
    """
    q = request.args.get("q", "").strip().lower()
    with db.session_scope() as s:
        merged = {
            row.tool_name: _public_tool_record_payload(row)
            for row in s.execute(
                select(ToolRecord).where(ToolRecord.deleted_at.is_(None)).order_by(ToolRecord.modified_at)
            ).scalars()
            if common.local_tool_is_public(row)
        }

    def matches(name: str, rec: dict) -> bool:
        keywords = rec.get("keywords")
        return (
            not q
            or any(q in str(rec.get(f, "")).lower() for f in ("title", "description"))
            or q in name.lower()
            or any(q in str(k).lower() for k in (keywords if isinstance(keywords, list) else []))
        )

    results = [{"name": name, **rec} for name, rec in merged.items() if matches(name, rec)]
    return jsonify({"count": len(results), "results": results})


@v1_bp.route("/v1/recent/owners/")
def v1_recent_owners() -> Response:
    """Bulk-resolve Recent table owner labels through the shared ToolsDB cache.

    Public and unauthenticated, but every cache miss costs an upstream Toolhub
    request, so this is the one read endpoint that can amplify traffic. It is
    rate limited per client like the /api/ proxy, and capped again by a
    per-request fetch budget so a single allowed call cannot fan out into
    OWNER_MAX_NAMES upstream requests.
    """
    if security.read_rate_limited(request.remote_addr):
        return common.deny(HTTP_TOO_MANY, "rate limit exceeded")
    names = request.args.getlist("tool")
    csv_names = request.args.get("tools", "")
    if csv_names:
        names.extend(csv_names.split(","))
    return jsonify(recent_owners.resolve_owners(names, fetch_budget=recent_owners.OWNER_FETCH_BUDGET))


@v1_bp.route("/toolinfo.json")
def toolinfo_feed() -> Response:
    """Serve the public toolinfo feed of locally-registered tools.

    The official Toolhub crawler can ingest this feed (docs/PRODUCTION.md
    §1.3 — we feed the ecosystem instead of forking it).
    """
    with db.session_scope() as s:
        merged = {
            row.tool_name: _public_tool_record_payload(row)
            for row in s.execute(
                select(ToolRecord).where(ToolRecord.deleted_at.is_(None)).order_by(ToolRecord.modified_at)
            ).scalars()
            if common.local_tool_is_public(row)
        }

    def entry(name: str, rec: dict) -> dict:
        # Defensive reads: writes are validated (common.clean_tool_record), but a bad
        # legacy row must degrade to an empty field, never break the feed.
        keywords = rec.get("keywords")
        wikis = rec.get("forWikis")
        return {
            "name": f"toolhub-evolved-{name}",
            "title": str(rec.get("title") or name),
            "description": str(rec.get("description") or ""),
            "url": str(rec.get("url") or ""),
            "keywords": ",".join(str(k) for k in keywords) if isinstance(keywords, list) else "",
            "repository": rec.get("repository") or None,
            "license": rec.get("license") or None,
            "tool_type": rec.get("toolType") or None,
            "for_wikis": wikis if isinstance(wikis, list) else [],
            "_schema": "/toolinfo/1.2.2",
        }

    feed = [entry(name, rec) for name, rec in merged.items() if str(rec.get("url") or "").startswith("https://")]
    return jsonify(feed)
