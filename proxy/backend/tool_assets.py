# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch and serve rebuildable same-origin tool icon cache entries."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import requests
from sqlalchemy import select

from backend import db, outbound
from backend.models import CatalogToolProjection, ToolAssetCache, utcnow

ALLOWED_CONTENT_TYPES = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}
MAX_CANDIDATES = 200
# Tools settled as "this tool declares no icon" per run. That verdict is decided
# entirely from the projection the scan has already read -- no request is made
# and no file is written -- so it does not belong under the fetch limit and
# never did. Sharing that limit is what put the whole wiki lane behind a
# hundred-an-hour queue sized for downloads: weeks to write rows that cost
# nothing. Bounded anyway, at a size that drains the current backlog in a
# morning, so one run stays a predictable unit of work on a database two dozen
# other jobs share.
MAX_SETTLEMENTS = 5000
# Rows per fetch for the projection scan; see `refresh_candidates`.
STREAM_BATCH_SIZE = 500
# Toolhub's toolinfo schema asks for a Wikimedia Commons file page as a tool's
# icon -- https://commons.wikimedia.org/wiki/File:Adiutor_icon.svg and the like
# -- so the URL a well-formed record declares is a description page, which is
# HTML, and not the image an <img> needs. Every icon this cache has ever failed
# on was one of those, 80 tools' worth, each retried on backoff forever against
# a page whose content type will never change. `Special:FilePath` redirects a
# file title to the file itself, which is the one resolution step between the
# two.
WIKI_PATH_PREFIX = "/wiki/"
WIKI_FILE_PREFIXES = ("file:", "image:")
FILE_PATH_TITLE = "Special:FilePath/"
# A raster icon is often a full screenshot and larger than the fetch budget, so
# the wiki is asked to scale it. Vectors are left whole: a width would rasterize
# them, and an SVG is small enough to take as it is.
THUMBNAIL_WIDTH = 512
VECTOR_SUFFIX = ".svg"
CALLER = outbound.Caller(
    user_agent="toolhub-evolved/0.2 (https://toolhub-evolved.toolforge.org)",
    accept=", ".join(ALLOWED_CONTENT_TYPES),
    scheme_error="icon URL must be public HTTPS",
)


def cache_dir() -> Path:
    default = str(Path(tempfile.gettempdir()) / "toolhub-evolved-assets")
    value = os.getenv("TOOLHUB_ASSET_CACHE_DIR", default)
    return Path(value).expanduser().resolve()


def _clean_name(value: Any) -> str:  # noqa: ANN401
    return str(value or "").strip()[:255]


def _wiki_file_url(url: str) -> str:
    """Resolve a wiki file-description page to a URL for the file itself.

    Anything that is not such a page is returned untouched, and the rewrite
    stays on the host the record named, so this widens no reach: it only stops
    asking a wiki for an article when what is wanted is an image.
    """
    parts = urlsplit(url)
    if not parts.path.startswith(WIKI_PATH_PREFIX):
        return url
    title = unquote(parts.path[len(WIKI_PATH_PREFIX) :])
    prefix = next((item for item in WIKI_FILE_PREFIXES if title[: len(item)].casefold() == item), "")
    name = title[len(prefix) :].strip() if prefix else ""
    if not name:
        return url
    query = "" if name.casefold().endswith(VECTOR_SUFFIX) else f"width={THUMBNAIL_WIDTH}"
    path = f"{WIKI_PATH_PREFIX}{FILE_PATH_TITLE}{quote(name, safe='')}"
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def _scaled_wiki_file_url(url: str) -> str:
    """Ask a wiki to scale a file it is already being asked for, or say it cannot."""
    parts = urlsplit(url)
    if parts.query or not parts.path.startswith(f"{WIKI_PATH_PREFIX}{FILE_PATH_TITLE}"):
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, f"width={THUMBNAIL_WIDTH}", ""))


def _fetch_icon(session: requests.Session, url: str) -> tuple[outbound.BoundedResponse, str]:
    """Fetch one icon, retrying once for a scaled copy the wiki can render.

    Vectors are asked for whole because a width would rasterize them, but a
    handful of them are drawings large enough to exceed the fetch budget. For
    those the wiki can produce a bounded raster of the same file, which is a
    better answer than a tool that never gets an icon at all.
    """
    try:
        response = outbound.fetch_bounded_response(session, url, policy=outbound.PUBLIC_IMAGE, caller=CALLER)
        return response, _content_suffix(response.content_type)
    except ValueError:
        scaled = _scaled_wiki_file_url(url)
        if scaled == url:
            raise
    response = outbound.fetch_bounded_response(session, scaled, policy=outbound.PUBLIC_IMAGE, caller=CALLER)
    return response, _content_suffix(response.content_type)


def _icon_source(row: Any) -> tuple[str, str]:  # noqa: ANN401 - projection entity or a two-column Row
    """Resolve a projection's declared icon URL and which source supplied it.

    Typed loosely because `refresh_candidates` hands this a `Row` of just
    `effective_record` and `provenance` rather than the whole entity; both
    expose the two attributes this reads by the same names.
    """
    record = row.effective_record if isinstance(row.effective_record, dict) else {}
    url = str(record.get("icon") or "").strip()
    evidence = row.provenance.get("icon", []) if isinstance(row.provenance, dict) else []
    source = next((str(item.get("source") or "") for item in evidence if item.get("effective")), "")
    return _wiki_file_url(url), source or "official_toolhub"


def _store_file(body: bytes, suffix: str) -> tuple[str, str]:
    digest = hashlib.sha256(body).hexdigest()
    target_dir = cache_dir()
    target_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    target = target_dir / f"{digest}{suffix}"
    if not target.exists():
        temporary = target_dir / f".{digest}.tmp"
        temporary.write_bytes(body)
        temporary.replace(target)
    return digest, str(target)


def _content_suffix(content_type: str) -> str:
    suffix = ALLOWED_CONTENT_TYPES.get(content_type)
    if suffix is None:
        message = f"unsupported icon content type: {content_type or 'missing'}"
        raise ValueError(message)
    return suffix


def refresh_tool(tool_name: str, *, session: requests.Session | None = None) -> dict[str, Any]:
    name = _clean_name(tool_name)
    if not name:
        return {"toolName": "", "status": "skipped"}
    with db.session_scope() as s:
        projection = s.get(CatalogToolProjection, name)
        if projection is None:
            return {"toolName": name, "status": "missing_projection"}
        url, source = _icon_source(projection)
    if not url:
        with db.session_scope() as s:
            row = s.get(ToolAssetCache, name) or ToolAssetCache(tool_name=name)
            s.add(row)
            row.source_url = ""
            row.source_type = source
            row.status = "missing"
            row.checked_at = utcnow()
            row.next_attempt_at = None
            row.last_error = None
        return {"toolName": name, "status": "missing"}
    try:
        response, suffix = _fetch_icon(session or requests.Session(), url)
        digest, path = _store_file(response.body, suffix)
    except (requests.RequestException, OSError, ValueError) as exc:
        with db.session_scope() as s:
            row = s.get(ToolAssetCache, name) or ToolAssetCache(tool_name=name)
            s.add(row)
            row.source_url = url
            row.source_type = source
            row.status = "error"
            row.attempts = (row.attempts or 0) + 1
            row.checked_at = utcnow()
            row.next_attempt_at = utcnow() + timedelta(hours=min(24, 2 ** min(row.attempts, 4)))
            row.last_error = str(exc)[:1000]
        return {"toolName": name, "status": "error", "error": str(exc)[:1000]}
    with db.session_scope() as s:
        row = s.get(ToolAssetCache, name) or ToolAssetCache(tool_name=name)
        s.add(row)
        row.source_url = url
        row.source_type = source
        row.content_type = response.content_type
        row.size_bytes = len(response.body)
        row.sha256 = digest
        row.cached_path = path
        row.etag = response.etag
        row.last_modified = response.last_modified
        row.status = "ready"
        row.checked_at = utcnow()
        row.next_attempt_at = None
        row.attempts = 0
        row.last_error = None
    return {"toolName": name, "status": "ready", "bytes": len(response.body), "sha256": digest}


def _settle_missing(settlements: list[tuple[str, str]]) -> int:
    """Record "this tool declares no icon" for tools that need no request to decide.

    `refresh_tool` reaches the same verdict, but it re-reads the projection to
    do it and is called one tool at a time under the fetch limit. The scan
    above has already read the only two columns the verdict depends on, so
    these rows are written straight from it, in chunks rather than one
    transaction, because a single statement over the whole wiki lane would hold
    row locks across a table the projection refresh is also writing.
    """
    written = 0
    for start in range(0, len(settlements), STREAM_BATCH_SIZE):
        chunk = settlements[start : start + STREAM_BATCH_SIZE]
        with db.session_scope() as s:
            for name, source in chunk:
                row = s.get(ToolAssetCache, name) or ToolAssetCache(tool_name=name)
                s.add(row)
                row.source_url = ""
                row.source_type = source
                row.status = "missing"
                row.checked_at = utcnow()
                row.next_attempt_at = None
                row.last_error = None
                written += 1
    return written


def refresh_candidates(limit: int = MAX_CANDIDATES) -> dict[str, int]:
    """Refresh what needs a request, and settle what does not, under separate bounds.

    `ready` counts icons actually fetched. It used to count `missing` too --
    `result["status"] in {"ready", "missing"}` -- which reported "ready: 100"
    every hour for a queue that was downloading nothing at all, and hid the
    fact that the limit was being spent on rows rather than requests.
    """
    bounded = max(1, min(MAX_CANDIDATES, int(limit or 1)))
    candidates: list[str] = []
    settlements: list[tuple[str, str]] = []
    with db.session_scope() as s:
        # Columns, not entities, and the projection scan streams. This loop
        # keeps only tool names, but selecting `CatalogToolProjection` loaded
        # four JSON blobs and `search_text` per row -- ~10KB each -- and
        # `ToolAssetCache` whole on top of it. Once discovery opened up to
        # every Wikimedia project the projection table outgrew the job's
        # memory, and every hourly tick was OOM-killed for a day. `yield_per`
        # keeps peak memory at one batch of projections however far the
        # catalogue grows; the asset side stays a dict because the loop needs
        # random access to it.
        assets = {
            row.tool_name: row
            for row in s.execute(
                select(
                    ToolAssetCache.tool_name,
                    ToolAssetCache.source_url,
                    ToolAssetCache.status,
                    ToolAssetCache.next_attempt_at,
                )
            )
        }
        projections = s.execute(
            select(
                CatalogToolProjection.tool_name,
                CatalogToolProjection.effective_record,
                CatalogToolProjection.provenance,
            )
            .order_by(CatalogToolProjection.tool_name)
            .execution_options(yield_per=STREAM_BATCH_SIZE)
        )
        for projection in projections:
            url, source = _icon_source(projection)
            asset = assets.get(projection.tool_name)
            retry_ready = asset is not None and (asset.next_attempt_at is None or asset.next_attempt_at <= utcnow())
            if not (
                asset is None
                or asset.source_url != url
                or asset.status == "pending"
                or (asset.status == "error" and retry_ready)
            ):
                continue
            # Which list decides whether this tool costs a request. Neither the
            # user-script nor the gadget lane publishes an `icon`, so almost
            # every wiki tool lands in `settlements` and is finished without
            # touching the network.
            if url:
                candidates.append(projection.tool_name)
            else:
                settlements.append((projection.tool_name, source))
    missing = _settle_missing(settlements[:MAX_SETTLEMENTS])
    ready = errors = 0
    http = requests.Session()
    for name in candidates[:bounded]:
        result = refresh_tool(name, session=http)
        ready += result["status"] == "ready"
        errors += result["status"] == "error"
    return {
        "candidates": len(candidates) + len(settlements),
        "fetches": len(candidates),
        "processed": min(len(candidates), bounded),
        "ready": ready,
        "errors": errors,
        "settled": missing,
        "settlements": len(settlements),
    }


def cached_asset(tool_name: str) -> tuple[bytes, str, str] | None:
    name = _clean_name(tool_name)
    with db.session_scope() as s:
        row = s.get(ToolAssetCache, name)
    if row is None or row.status != "ready" or not row.cached_path:
        return None
    root = cache_dir()
    path = Path(row.cached_path).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path.read_bytes(), row.content_type, row.sha256
