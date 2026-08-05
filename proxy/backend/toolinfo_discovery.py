# SPDX-License-Identifier: GPL-3.0-or-later
"""Automated discovery of toolinfo.json locations for official Toolhub tools."""

import json
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from defusedxml import ElementTree
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import db, graph_enrichment, outbound, toolhub
from backend.author_claims import dedupe_strings
from backend.models import ToolAuthorClaim, ToolinfoDiscovery, ToolinfoDiscoveryMeta, utcnow
from backend.sync import SOURCE_LOCAL, SYNC_EVOLVED_REAL, clean_error

UA = "toolhub-evolved-toolinfo-discovery/1.0 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
MAX_URL = 2000
MAX_ITEMS_PER_TOOLINFO = 200
MAX_SITEMAP_LOCS = 200
_JSON_CALLER = outbound.Caller(UA, "application/json", "only public https URLs are discovered")
_XML_CALLER = outbound.Caller(UA, "application/xml,text/xml", "only public https URLs are discovered")
HTTP_NOT_FOUND = 404
STATUS_PENDING = "pending"
STATUS_FOUND = "found"
STATUS_NOT_FOUND = "not_found"
STATUS_ERROR = "error"
STATUS_NO_URL = "no_url"
FOUND_TTL = timedelta(days=7)
NOT_FOUND_TTL = timedelta(days=1)
ERROR_TTL = timedelta(hours=1)
TOOLHUB_LIST_PAGE_SIZE = 100
TOOLHUB_LIST_CURSOR_KEY = "toolhub_tools_page"


def _fetch_body(session: requests.Session, url: str, *, accept: str) -> bytes:
    """Fetch a discovered document under the strict public-fetch policy.

    Discovery walks URLs derived from tool metadata, so the target is not ours to
    trust: https only, non-public addresses refused, redirects refused, body
    capped. See backend.outbound for why each of those is there.
    """
    caller = _XML_CALLER if "xml" in accept else _JSON_CALLER
    return outbound.fetch_bounded(session, url, policy=outbound.STRICT_PUBLIC, caller=caller)


def fetch_toolinfo_json_once(url: str, session: requests.Session | None = None) -> object:
    """Fetch one candidate toolinfo.json document."""
    active_session = session or requests.Session()
    return json.loads(_fetch_body(active_session, url, accept="application/json").decode("utf-8"))


def fetch_sitemap_xml_once(url: str, session: requests.Session | None = None) -> str:
    """Fetch one candidate sitemap XML document."""
    active_session = session or requests.Session()
    return _fetch_body(active_session, url, accept="application/xml,text/xml").decode("utf-8")


def _exception_status(exc: BaseException) -> int | None:
    """Extract an HTTP status code from requests exceptions when available."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _https_upgraded(raw_url: str) -> str:
    """Return `raw_url` with http upgraded to https on Wikimedia Cloud hosts.

    Toolhub records some Cloud tools with http:// URLs, but those hosts serve
    https — the plain-http entry is stale metadata, not a real endpoint. Building
    the candidate as https fixes those without teaching the fetch policy to accept
    http, which would weaken the DNS-rebinding guarantee for every user-registered
    URL in order to fix a URL-construction problem.
    """
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() != "http" or not outbound.is_split_horizon_public_host((parsed.hostname or "").lower()):
        return raw_url
    return urlunparse(parsed._replace(scheme="https"))


def _origin(raw_url: str) -> str:
    parsed = urlparse(_https_upgraded(raw_url))
    return f"{parsed.scheme.lower()}://{parsed.netloc}"


def _root_toolinfo_url(raw_url: str) -> str:
    url = _https_upgraded(raw_url)
    parsed = urlparse(url)
    return url if parsed.path.rstrip("/").endswith("toolinfo.json") else f"{_origin(url)}/toolinfo.json"


def _sitemap_url(raw_url: str) -> str:
    return f"{_origin(raw_url)}/sitemap.xml"


def _toolinfo_names(data: object) -> list[str]:
    """Return compact tool names found in a toolinfo object or array."""
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data[:MAX_ITEMS_PER_TOOLINFO]
    else:
        return []
    return dedupe_strings([item.get("name") for item in items if isinstance(item, dict)])


def _sitemap_toolinfo_urls(xml_text: str, *, sitemap_url: str, origin: str) -> list[str]:
    """Return same-origin toolinfo.json URLs advertised by a sitemap."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    origin_parsed = urlparse(origin)
    urls: list[str] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "loc" or not node.text:
            continue
        candidate = urljoin(sitemap_url, node.text.strip())
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or parsed.netloc != origin_parsed.netloc:
            continue
        if not parsed.path.rstrip("/").endswith("toolinfo.json"):
            continue
        if len(candidate) > MAX_URL:
            continue
        urls.append(candidate)
        if len(urls) >= MAX_SITEMAP_LOCS:
            break
    return dedupe_strings(urls)


def _discovery_attempt(
    url: str,
    method: str,
    attempts: list[dict],
    session: requests.Session,
) -> tuple[object | None, bool]:
    """Try one candidate URL, recording a normalized discovery attempt."""
    try:
        data = fetch_toolinfo_json_once(url, session)
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        status = _exception_status(exc)
        attempts.append({"url": url, "method": method, "ok": False, "status": status, "error": clean_error(str(exc))})
        return None, status == HTTP_NOT_FOUND
    attempts.append({"url": url, "method": method, "ok": True})
    return data, False


def discover_toolinfo_url(
    raw_url: str,
    session: requests.Session | None = None,
    *,
    tool_name: str = "",
) -> dict:
    """Discover a concrete toolinfo.json URL by checking root first, then sitemap after root 404."""
    url = raw_url.strip()
    active_session = session or requests.Session()
    root_url = _root_toolinfo_url(url)
    attempts: list[dict] = []
    data, root_not_found = _discovery_attempt(root_url, "root", attempts, active_session)
    if data is not None:
        return _found_payload(url, root_url, "root", data, attempts, tool_name=tool_name)
    if not root_not_found:
        return {
            "ok": False,
            "status": STATUS_ERROR,
            "inputUrl": url,
            "attempts": attempts,
            "lastError": attempts[-1].get("error") or "toolinfo.json could not be fetched",
        }

    sitemap_url = _sitemap_url(url)
    try:
        sitemap_xml = fetch_sitemap_xml_once(sitemap_url, active_session)
        attempts.append({"url": sitemap_url, "method": "sitemap", "ok": True})
    except (requests.RequestException, ValueError) as exc:
        attempts.append(
            {
                "url": sitemap_url,
                "method": "sitemap",
                "ok": False,
                "status": _exception_status(exc),
                "error": clean_error(str(exc)),
            }
        )
        return {
            "ok": False,
            "status": STATUS_NOT_FOUND,
            "inputUrl": url,
            "attempts": attempts,
            "lastError": "toolinfo.json not found at root and sitemap.xml could not be used",
        }

    for candidate in _sitemap_toolinfo_urls(sitemap_xml, sitemap_url=sitemap_url, origin=_origin(url)):
        data, _not_found = _discovery_attempt(candidate, "sitemap-toolinfo", attempts, active_session)
        if data is not None:
            return _found_payload(url, candidate, "sitemap", data, attempts, tool_name=tool_name)
    return {
        "ok": False,
        "status": STATUS_NOT_FOUND,
        "inputUrl": url,
        "attempts": attempts,
        "lastError": "toolinfo.json not found at root or in sitemap.xml",
    }


def _matching_record(data: object, tool_name: str) -> dict | None:
    if not tool_name:
        return None
    items = [data] if isinstance(data, dict) else data[:MAX_ITEMS_PER_TOOLINFO] if isinstance(data, list) else []
    target = tool_name.casefold()
    matching = next(
        (item for item in items if isinstance(item, dict) and str(item.get("name") or "").strip().casefold() == target),
        None,
    )
    if matching is None:
        return None
    fields = ("name", *graph_enrichment.FACET_FIELDS)
    return {field: matching[field] for field in fields if field in matching}


def _found_payload(  # noqa: PLR0913 - URL, method, document, attempts, and target are distinct evidence
    input_url: str,
    toolinfo_url: str,
    method: str,
    data: object,
    attempts: list[dict],
    *,
    tool_name: str = "",
) -> dict:
    payload = {
        "ok": True,
        "status": STATUS_FOUND,
        "method": method,
        "inputUrl": input_url,
        "toolinfoUrl": toolinfo_url,
        "toolNames": _toolinfo_names(data),
        "attempts": attempts,
    }
    matched = _matching_record(data, tool_name)
    if matched is not None:
        payload["toolRecord"] = matched
    return payload


def tool_discovery_candidate_url(tool: dict) -> str:
    """Return the best URL to probe for one official Toolhub tool."""
    for key in ("toolinfo_url", "toolinfoUrl"):
        value = tool.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = tool.get("url")
    return value.strip() if isinstance(value, str) else ""


def discovery_payload(row: ToolinfoDiscovery | None) -> dict:
    """Serialize one stored discovery row for owner-facing APIs."""
    if row is None:
        return {"status": STATUS_PENDING, "source": SOURCE_LOCAL, "syncStatus": SYNC_EVOLVED_REAL}
    return {
        "toolName": row.tool_name,
        "toolUrl": row.tool_url,
        "status": row.status or STATUS_PENDING,
        "method": row.method or "",
        "toolinfoUrl": row.toolinfo_url or "",
        "toolNames": row.tool_names if isinstance(row.tool_names, list) else [],
        "attempts": row.attempts if isinstance(row.attempts, list) else [],
        "checkedAt": _iso(row.checked_at),
        "expiresAt": _iso(row.expires_at),
        "lastError": row.last_error or "",
        "source": row.source or SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
    }


def _iso(value) -> str:  # noqa: ANN001 - accepts nullable datetimes from SQLAlchemy rows.
    return value.isoformat() + "Z" if value is not None else ""


def _expiry_for_status(status: str) -> datetime:
    now = utcnow()
    if status == STATUS_FOUND:
        return now + FOUND_TTL
    if status == STATUS_NOT_FOUND:
        return now + NOT_FOUND_TTL
    if status == STATUS_ERROR:
        return now + ERROR_TTL
    if status == STATUS_NO_URL:
        return now + NOT_FOUND_TTL
    return now


def upsert_pending(s: Session, *, tool_name: str, tool_url: str) -> ToolinfoDiscovery:
    """Ensure one discovered owner tool has a row ready for the background job."""
    row = s.execute(select(ToolinfoDiscovery).where(ToolinfoDiscovery.tool_name == tool_name)).scalar_one_or_none()
    if row is None:
        row = ToolinfoDiscovery(tool_name=tool_name, tool_url=tool_url[:MAX_URL], status=STATUS_PENDING)
        s.add(row)
        return row
    if tool_url and row.tool_url != tool_url[:MAX_URL]:
        row.tool_url = tool_url[:MAX_URL]
        row.status = STATUS_PENDING
        row.payload = None
        row.expires_at = utcnow()
    return row


def upsert_no_url(s: Session, *, tool_name: str, last_error: str) -> ToolinfoDiscovery:
    """Record that Toolhub has no usable URL from which Evolved can discover toolinfo.json."""
    row = s.execute(select(ToolinfoDiscovery).where(ToolinfoDiscovery.tool_name == tool_name)).scalar_one_or_none()
    if row is None:
        row = ToolinfoDiscovery(tool_name=tool_name, tool_url="", status=STATUS_NO_URL)
        s.add(row)
    row.status = STATUS_NO_URL
    row.method = None
    row.toolinfo_url = None
    row.tool_names = []
    row.payload = None
    row.attempts = []
    row.checked_at = utcnow()
    row.expires_at = _expiry_for_status(STATUS_NO_URL)
    row.last_error = clean_error(last_error)
    row.source = SOURCE_LOCAL
    row.sync_status = SYNC_EVOLVED_REAL
    return row


def upsert_result(s: Session, *, tool_name: str, tool_url: str, result: dict) -> ToolinfoDiscovery:
    """Persist one automated discovery result."""
    row = upsert_pending(s, tool_name=tool_name, tool_url=tool_url)
    status = str(result.get("status") or (STATUS_FOUND if result.get("ok") else STATUS_ERROR))
    row.status = status
    row.method = str(result.get("method") or "") or None
    row.toolinfo_url = str(result.get("toolinfoUrl") or "")[:MAX_URL] or None
    row.tool_names = result.get("toolNames") if isinstance(result.get("toolNames"), list) else []
    row.payload = result.get("toolRecord") if isinstance(result.get("toolRecord"), dict) else None
    row.attempts = result.get("attempts") if isinstance(result.get("attempts"), list) else []
    row.checked_at = utcnow()
    row.expires_at = _expiry_for_status(status)
    row.last_error = clean_error(str(result.get("lastError") or "")) or None
    row.source = SOURCE_LOCAL
    row.sync_status = SYNC_EVOLVED_REAL
    return row


def ensure_pending_for_candidates(candidates: dict[str, dict]) -> dict[str, dict]:
    """Create pending discovery rows for resolver candidates and return stored payloads."""
    tool_names = list(candidates)
    with db.session_scope() as s:
        for tool_name, entry in candidates.items():
            tool_url = tool_discovery_candidate_url(entry.get("tool") if isinstance(entry.get("tool"), dict) else {})
            if tool_url:
                upsert_pending(s, tool_name=tool_name, tool_url=tool_url)
            else:
                upsert_no_url(s, tool_name=tool_name, last_error="official Toolhub record has no URL to probe")
        rows = {
            row.tool_name: discovery_payload(row)
            for row in s.execute(select(ToolinfoDiscovery).where(ToolinfoDiscovery.tool_name.in_(tool_names))).scalars()
        }
    return {name: rows.get(name, discovery_payload(None)) for name in tool_names}


def _toolhub_detail_for_name(tool_name: str) -> dict | None:
    try:
        payload = toolhub.public_api_get(f"/api/tools/{quote(tool_name, safe='')}/")
    except (toolhub.ToolhubAPIError, requests.RequestException):
        return None
    return payload if isinstance(payload, dict) else None


def _claim_tool_names(limit: int) -> list[str]:
    with db.session_scope() as s:
        return [
            name
            for name in s.execute(select(ToolAuthorClaim.tool_name).group_by(ToolAuthorClaim.tool_name).limit(limit))
            .scalars()
            .all()
            if name
        ]


def _clean_tool_name(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _toolhub_tool_listing_page(page: int, *, page_size: int = TOOLHUB_LIST_PAGE_SIZE) -> tuple[list[dict], bool]:
    """Fetch one page from official Toolhub's canonical tool list."""
    payload = toolhub.public_api_get("/api/tools/", params={"page": page, "page_size": page_size})
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], False
    if not isinstance(payload, dict):
        return [], False
    results = payload.get("results")
    rows = [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []
    has_next = bool(payload.get("next"))
    return rows, has_next


def _meta_int(s: Session, key: str, default: int) -> int:
    row = s.get(ToolinfoDiscoveryMeta, key)
    if row is None:
        return default
    try:
        return max(1, int(row.value))
    except ValueError:
        return default


def _set_meta_int(s: Session, key: str, value: int) -> None:
    row = s.get(ToolinfoDiscoveryMeta, key)
    if row is None:
        row = ToolinfoDiscoveryMeta(key=key, value=str(value))
        s.add(row)
    row.value = str(max(1, value))
    row.updated_at = utcnow()


def _tool_url_from_listing_row(row: dict) -> str:
    tool_url = tool_discovery_candidate_url(row)
    if tool_url:
        return tool_url
    tool_name = _clean_tool_name(row.get("name"))
    detail = _toolhub_detail_for_name(tool_name) if tool_name else None
    return tool_discovery_candidate_url(detail or {})


def _seed_listing_row(row: dict) -> dict[str, int]:
    """Create or update discovery state from one official Toolhub listing row."""
    tool_name = _clean_tool_name(row.get("name"))
    if not tool_name:
        return {"seeded": 0, "skipped": 1, "errors": 0}
    try:
        tool_url = _tool_url_from_listing_row(row)
    except (toolhub.ToolhubAPIError, requests.RequestException):
        return {"seeded": 0, "skipped": 1, "errors": 1}
    with db.session_scope() as s:
        if not tool_url:
            upsert_no_url(s, tool_name=tool_name, last_error="official Toolhub record has no URL to probe")
            return {"seeded": 0, "skipped": 1, "errors": 0}
        before = s.execute(
            select(ToolinfoDiscovery).where(ToolinfoDiscovery.tool_name == tool_name)
        ).scalar_one_or_none()
        previous_url = before.tool_url if before is not None else None
        upsert_pending(s, tool_name=tool_name, tool_url=tool_url)
    return {"seeded": int(before is None or previous_url != tool_url[:MAX_URL]), "skipped": 0, "errors": 0}


def seed_from_toolhub_listing(
    limit: int = 100,
    *,
    page_size: int = TOOLHUB_LIST_PAGE_SIZE,
    max_pages: int = 1,
) -> dict[str, int]:
    """Seed discovery rows by walking official Toolhub tool-list pages over repeated job runs."""
    if limit <= 0 or max_pages <= 0:
        return {"seeded": 0, "skipped": 0, "errors": 0}
    effective_page_size = max(1, min(page_size, limit))
    with db.session_scope() as s:
        page = _meta_int(s, TOOLHUB_LIST_CURSOR_KEY, 1)

    seeded = skipped = errors = 0
    next_page = page
    pages_scanned = 0
    while seeded < limit and pages_scanned < max_pages:
        try:
            rows, has_next = _toolhub_tool_listing_page(next_page, page_size=effective_page_size)
        except (toolhub.ToolhubAPIError, requests.RequestException):
            errors += 1
            break
        pages_scanned += 1
        if not rows:
            next_page = 1
            break
        for row in rows:
            row_summary = _seed_listing_row(row)
            seeded += row_summary["seeded"]
            skipped += row_summary["skipped"]
            errors += row_summary["errors"]
            if seeded >= limit:
                break
        if not has_next:
            next_page = 1
            break
        next_page += 1

    with db.session_scope() as s:
        _set_meta_int(s, TOOLHUB_LIST_CURSOR_KEY, next_page)
    return {"seeded": seeded, "skipped": skipped, "errors": errors}


def refresh_known_discoveries(limit: int = 100) -> dict[str, int]:
    """Refresh stale/missing discovery rows and seed rows from known author claims."""
    refreshed = found = missing = errors = seeded = skipped = 0
    listing_summary = seed_from_toolhub_listing(limit=limit)
    seeded += listing_summary["seeded"]
    skipped += listing_summary["skipped"]
    errors += listing_summary["errors"]
    now = utcnow()
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolinfoDiscovery)
                .where(ToolinfoDiscovery.tool_url != "")
                .where((ToolinfoDiscovery.expires_at.is_(None)) | (ToolinfoDiscovery.expires_at <= now))
                .order_by(
                    ToolinfoDiscovery.expires_at.is_(None).desc(),
                    ToolinfoDiscovery.expires_at,
                    ToolinfoDiscovery.id,
                )
                .limit(limit)
            ).scalars()
        )
        queued_names = {row.tool_name for row in rows}

    for tool_name in _claim_tool_names(limit):
        if len(rows) >= limit:
            break
        if tool_name in queued_names:
            continue
        with db.session_scope() as s:
            existing = s.execute(
                select(ToolinfoDiscovery).where(ToolinfoDiscovery.tool_name == tool_name)
            ).scalar_one_or_none()
        if existing is not None and existing.expires_at is not None and existing.expires_at > now:
            continue
        detail = _toolhub_detail_for_name(tool_name)
        tool_url = tool_discovery_candidate_url(detail or {})
        if not tool_url:
            skipped += 1
            continue
        with db.session_scope() as s:
            rows.append(upsert_pending(s, tool_name=tool_name, tool_url=tool_url))
        seeded += 1

    session = requests.Session()
    for row in rows[:limit]:
        result = discover_toolinfo_url(row.tool_url, session, tool_name=row.tool_name)
        with db.session_scope() as s:
            upsert_result(s, tool_name=row.tool_name, tool_url=row.tool_url, result=result)
        graph_enrichment.refresh_tool_names([row.tool_name])
        refreshed += 1
        if result.get("status") == STATUS_FOUND:
            found += 1
        elif result.get("status") == STATUS_NOT_FOUND:
            missing += 1
        else:
            errors += 1
    return {
        "refreshed": refreshed,
        "seeded": seeded,
        "found": found,
        "missing": missing,
        "errors": errors,
        "skipped": skipped,
    }
