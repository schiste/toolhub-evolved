# SPDX-License-Identifier: GPL-3.0-or-later
"""Index official Toolhub crawler sources into the local evidence database."""

import ipaddress
import json
import socket
from datetime import UTC, datetime
from urllib.parse import unquote, urlparse

import requests
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend import db, toolhub
from backend.author_claims import dedupe_strings
from backend.models import ToolinfoSource, ToolinfoSourceItem, utcnow
from backend.sync import SOURCE_OFFICIAL, SYNC_ERROR, SYNC_OFFICIAL, clean_error, clean_int

UA = "toolhub-evolved-source-indexer/1.0 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
TIMEOUT = (5, 60)
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_ITEMS_PER_SOURCE = 10000
MAX_URL = 2000
PUBLIC_INTERNAL_HOST_SUFFIXES = (".toolforge.org", ".wmflabs.org")
SOURCE_STATUS_PENDING = "pending"
SOURCE_STATUS_VALID = "valid"
SOURCE_STATUS_INVALID = "invalid"
SOURCE_STATUS_ERROR = "error"
KIND_TOOLSADMIN = "toolsadmin"
KIND_USER_SCRIPT_FEED = "user_script_feed"
KIND_WIKI_RAW = "wiki_raw"
KIND_GITHUB_RAW = "github_raw"
KIND_SELF_HOSTED_TOOLINFO = "self_hosted_toolinfo"
KIND_OTHER_FEED = "other_feed"

SOURCE_LABELS = {
    KIND_TOOLSADMIN: "Toolsadmin feed",
    KIND_USER_SCRIPT_FEED: "User script feed",
    KIND_WIKI_RAW: "Wiki raw feed",
    KIND_GITHUB_RAW: "GitHub raw toolinfo",
    KIND_SELF_HOSTED_TOOLINFO: "Self-hosted toolinfo",
    KIND_OTHER_FEED: "Official crawler feed",
}


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") + "Z" if value is not None else ""


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)


def _text(value: object, limit: int = 255) -> str:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else ""


def _tool_name(value: object) -> str:
    return _text(value, 255)


def classify_source_url(url: str) -> str:
    """Return the source bucket shown to maintainers for one official crawler URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    query = unquote(parsed.query.lower())
    if host == "toolsadmin.wikimedia.org" and "/tools/toolinfo/" in path:
        return KIND_TOOLSADMIN
    if host in {"tools-static.wmflabs.org", "tools-static.toolforge.org"} and "toolinfo-scraper" in path:
        return KIND_USER_SCRIPT_FEED
    if host == "raw.githubusercontent.com":
        return KIND_GITHUB_RAW
    if "action=raw" in query or "ctype=application/json" in query:
        return KIND_WIKI_RAW
    if path.rstrip("/").endswith("toolinfo.json"):
        return KIND_SELF_HOSTED_TOOLINFO
    return KIND_OTHER_FEED


def source_label(source_kind: str) -> str:
    """Return a stable, user-facing label for one source kind."""
    return SOURCE_LABELS.get(source_kind, SOURCE_LABELS[KIND_OTHER_FEED])


def _is_public_ingress_host(host: str) -> bool:
    """Return whether a public Wikimedia Cloud hostname may resolve internally."""
    return host in {"toolforge.org", "wmflabs.org"} or host.endswith(PUBLIC_INTERNAL_HOST_SUFFIXES)


def _require_public_http(url: str) -> None:
    """Reject non-public HTTP(S) crawler feeds before fetching them."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        msg = f"{url}: only public http or https crawler URLs are indexed"
        raise ValueError(msg)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        msg = f"{url}: cannot resolve host ({exc})"
        raise ValueError(msg) from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global and not _is_public_ingress_host(host):
            msg = f"{url}: resolves to a non-public address - refused"
            raise ValueError(msg)


def fetch_toolinfo_feed_once(url: str, session: requests.Session | None = None) -> object:
    """Fetch one official crawler feed with SSRF guards and a hard size cap."""
    _require_public_http(url)
    active_session = session or requests.Session()
    with active_session.get(
        url,
        headers={"User-Agent": UA, "Accept": "application/json"},
        timeout=TIMEOUT,
        stream=True,
        allow_redirects=False,
    ) as resp:
        if resp.is_redirect or resp.is_permanent_redirect:
            msg = f"{url}: redirects are not followed - index the final URL"
            raise ValueError(msg)
        resp.raise_for_status()
        body = bytearray()
        for chunk in resp.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                msg = f"{url}: response larger than {MAX_BODY_BYTES} bytes"
                raise ValueError(msg)
    return json.loads(bytes(body).decode("utf-8"))


def _registered_rows_from_payload(payload: object) -> tuple[list[dict], bool]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], False
    if not isinstance(payload, dict):
        return [], False
    results = payload.get("results")
    rows = [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []
    return rows, bool(payload.get("next"))


def official_crawler_url_rows(page_size: int = 500) -> list[dict]:
    """Return all official crawler URL registrations exposed by Toolhub."""
    rows: list[dict] = []
    page = 1
    while True:
        payload = toolhub.public_api_get("/api/crawler/urls/", params={"page": page, "page_size": page_size})
        page_rows, has_next = _registered_rows_from_payload(payload)
        rows.extend(page_rows)
        if not has_next:
            return rows
        page += 1


def _username(value: object) -> str:
    if isinstance(value, dict):
        return _text(value.get("username") or value.get("name"))
    return _text(value)


def _created_by_user_id(value: object) -> int | None:
    return clean_int(value.get("id")) if isinstance(value, dict) else None


def _row_url(row: dict) -> str:
    return _text(row.get("url"), MAX_URL)


def _upsert_registered_row(s: Session, row: dict, now: datetime) -> bool:
    url = _row_url(row)
    if not url:
        return False
    official_id = clean_int(row.get("id"))
    source = None
    if official_id is not None:
        source = s.execute(select(ToolinfoSource).where(ToolinfoSource.official_id == official_id)).scalar_one_or_none()
    if source is None:
        source = s.execute(select(ToolinfoSource).where(ToolinfoSource.url == url)).scalar_one_or_none()
    if source is None:
        source = ToolinfoSource(url=url)
        s.add(source)
    source.official_id = official_id
    source.url = url
    source.source_kind = classify_source_url(url)
    source.created_by_username = _username(row.get("created_by") or row.get("createdBy"))
    source.created_by_user_id = _created_by_user_id(row.get("created_by") or row.get("createdBy"))
    source.created_date = _parse_iso(row.get("created_date") or row.get("createdDate") or row.get("created"))
    source.last_seen_at = now
    source.source = SOURCE_OFFICIAL
    if source.sync_status != SYNC_ERROR:
        source.sync_status = SYNC_OFFICIAL
    return True


def sync_registered_sources() -> dict[str, int]:
    """Mirror the official crawler URL registry into local source rows."""
    rows = official_crawler_url_rows()
    now = utcnow()
    registered = skipped = 0
    with db.session_scope() as s:
        for row in rows:
            if _upsert_registered_row(s, row, now):
                registered += 1
            else:
                skipped += 1
    return {"registered": registered, "skipped": skipped}


def _item_rows(data: object) -> list[dict]:
    if isinstance(data, dict):
        raw_items = [data]
    elif isinstance(data, list):
        raw_items = data[:MAX_ITEMS_PER_SOURCE]
    else:
        msg = "toolinfo feed must be a JSON object or array"
        raise TypeError(msg)
    items = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = _tool_name(item.get("name"))
        if not name or name.lower() in seen:
            continue
        if not all(_text(item.get(field)) for field in ("title", "description", "url")):
            continue
        seen.add(name.lower())
        items.append(
            {
                "tool_name": name,
                "title": _text(item.get("title")),
                "tool_url": _text(item.get("url"), MAX_URL),
                "payload": item,
            }
        )
    return items


def _mark_source_error(source_id: int, error: str) -> None:
    with db.session_scope() as s:
        source = s.get(ToolinfoSource, source_id)
        if source is None:
            return
        source.last_fetched_at = utcnow()
        source.status = SOURCE_STATUS_ERROR
        source.valid = False
        source.last_error = clean_error(error)
        source.sync_status = SYNC_ERROR


def _store_source_items(source_id: int, items: list[dict]) -> int:
    now = utcnow()
    with db.session_scope() as s:
        source = s.get(ToolinfoSource, source_id)
        if source is None:
            return 0
        s.execute(delete(ToolinfoSourceItem).where(ToolinfoSourceItem.source_id == source_id))
        source.last_fetched_at = now
        source.status = SOURCE_STATUS_VALID if items else SOURCE_STATUS_INVALID
        source.valid = bool(items)
        source.item_count = len(items)
        source.last_error = None if items else "no valid named toolinfo items"
        source.source = SOURCE_OFFICIAL
        source.sync_status = SYNC_OFFICIAL if items else SYNC_ERROR
        for item in items:
            s.add(
                ToolinfoSourceItem(
                    tool_name=item["tool_name"],
                    source_id=source_id,
                    source_url=source.url,
                    title=item["title"],
                    tool_url=item["tool_url"],
                    payload=item["payload"],
                    last_seen_at=now,
                    source=SOURCE_OFFICIAL,
                    sync_status=SYNC_OFFICIAL,
                )
            )
        return len(items)


def _source_targets(limit: int) -> list[tuple[int, str]]:
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolinfoSource)
                .order_by(
                    ToolinfoSource.last_fetched_at.is_not(None),
                    ToolinfoSource.last_fetched_at,
                    ToolinfoSource.id,
                )
                .limit(limit)
            ).scalars()
        )
        return [(row.id, row.url) for row in rows]


def index_official_crawler_sources(limit: int = 150) -> dict[str, int]:
    """Fetch official registered feeds and persist per-tool source mappings."""
    registry = sync_registered_sources()
    fetched = valid = invalid = errors = items = 0
    session = requests.Session()
    for source_id, url in _source_targets(max(1, limit)):
        try:
            data = fetch_toolinfo_feed_once(url, session)
            item_rows = _item_rows(data)
            item_count = _store_source_items(source_id, item_rows)
        except (requests.RequestException, TypeError, ValueError, json.JSONDecodeError) as exc:
            _mark_source_error(source_id, str(exc))
            fetched += 1
            errors += 1
            continue
        fetched += 1
        items += item_count
        if item_count:
            valid += 1
        else:
            invalid += 1
    return {
        "registered": registry["registered"],
        "skipped": registry["skipped"],
        "fetched": fetched,
        "valid": valid,
        "invalid": invalid,
        "errors": errors,
        "items": items,
    }


def source_payload(item: ToolinfoSourceItem, source: ToolinfoSource) -> dict:
    """Serialize source evidence for owner-facing APIs."""
    return {
        "toolName": item.tool_name,
        "title": item.title or "",
        "toolUrl": item.tool_url or "",
        "sourceUrl": source.url,
        "sourceId": source.id,
        "officialId": source.official_id,
        "sourceKind": source.source_kind,
        "sourceLabel": source_label(source.source_kind),
        "createdBy": source.created_by_username or "",
        "createdDate": _iso(source.created_date),
        "lastSeenAt": _iso(item.last_seen_at),
        "lastFetchedAt": _iso(source.last_fetched_at),
        "status": source.status,
        "valid": bool(source.valid),
        "itemCount": source.item_count,
        "lastError": source.last_error or "",
        "source": source.source or SOURCE_OFFICIAL,
        "syncStatus": source.sync_status or SYNC_OFFICIAL,
    }


def sources_for_tools(tool_names: list[str]) -> dict[str, dict]:
    """Return the best indexed official crawler source for each requested tool."""
    names = dedupe_strings([_tool_name(name) for name in tool_names])
    if not names:
        return {}
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolinfoSourceItem, ToolinfoSource)
                .join(ToolinfoSource, ToolinfoSourceItem.source_id == ToolinfoSource.id)
                .where(ToolinfoSourceItem.tool_name.in_(names))
                .order_by(ToolinfoSource.official_id.is_(None), ToolinfoSource.official_id, ToolinfoSource.id)
            ).all()
        )
        out: dict[str, dict] = {}
        for item, source in rows:
            out.setdefault(item.tool_name, source_payload(item, source))
        return out
