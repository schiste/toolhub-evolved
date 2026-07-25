# SPDX-License-Identifier: GPL-3.0-or-later
"""Server-side toolinfo crawler (Toolforge Jobs framework; see jobs.yaml).

Fetches every registered toolinfo.json URL (the union across users), validates
the records, and upserts them as locally-registered tools attributed to the
user who registered the URL. Per the resolved data architecture
(docs/PRODUCTION.md §0), a name that already exists upstream on Toolhub is
skipped: the live API stays that record's source of truth — we never store a
shadow copy of upstream data.
"""

import ipaddress
import json
import os
import socket
import sys
from urllib.parse import urlparse

import requests
from sqlalchemy import select

from backend import DEFAULT_DB_URL, db
from backend.models import CrawlerRun, CrawlerUrl, ToolRecord, utcnow

UPSTREAM_TOOL = "https://toolhub.wikimedia.org/api/tools/"
UA = "toolhub-evolved-crawler/1.0 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
TIMEOUT = 20
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_ITEMS_PER_URL = 200
HTTP_NOT_FOUND = 404


def _require_public_https(url: str) -> None:
    """Reject non-https URLs and hosts that resolve to non-public addresses.

    Registered URLs are user-supplied, so the scheduled job must never be
    turned into an SSRF probe of the Toolforge network: loopback, private,
    link-local, reserved and multicast destinations are all refused, and
    redirects are never followed (below) so a public host can't bounce the
    fetch somewhere internal. (Resolution happens just before the fetch; a
    DNS-rebinding TOCTOU window remains, which is why the job also only ever
    speaks HTTPS — an internal service would still need a valid certificate.)
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        msg = f"{url}: only https toolinfo URLs are crawled"
        raise ValueError(msg)
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        msg = f"{url}: cannot resolve host ({exc})"
        raise ValueError(msg) from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            msg = f"{url}: resolves to a non-public address — refused"
            raise ValueError(msg)


def _fetch_json(session: requests.Session, url: str) -> object:
    """GET a toolinfo URL with SSRF guards and a hard size cap; raises on failure."""
    _require_public_https(url)
    with session.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, stream=True, allow_redirects=False) as resp:
        if resp.is_redirect or resp.is_permanent_redirect:
            msg = f"{url}: redirects are not followed — register the final URL"
            raise ValueError(msg)
        resp.raise_for_status()
        body = bytearray()
        for chunk in resp.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                msg = f"{url}: response larger than {MAX_BODY_BYTES} bytes"
                raise ValueError(msg)
    return json.loads(bytes(body).decode("utf-8"))


def exists_upstream(session: requests.Session, name: str) -> bool:
    """Report whether the official Toolhub already has this tool name.

    Errors count as "exists" so a Toolhub outage can never cause us to shadow
    an upstream record; the URL is simply retried on the next scheduled run.
    """
    try:
        resp = session.get(f"{UPSTREAM_TOOL}{name}/", headers={"User-Agent": UA}, timeout=TIMEOUT)
    except requests.RequestException:
        return True
    return resp.status_code != HTTP_NOT_FOUND


def normalize_record(item: dict) -> dict | None:
    """Map a toolinfo item to the SPA's compact record shape (None when invalid)."""
    if not all(isinstance(item.get(f), str) and item[f] for f in ("name", "title", "description", "url")):
        return None
    keywords = item.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    return {
        "title": item["title"],
        "description": item["description"],
        "url": item["url"],
        "repository": item.get("repository") or None,
        "license": item.get("license") or None,
        "toolType": item.get("tool_type") or None,
        "keywords": keywords,
        "forWikis": item.get("for_wikis", []),
        "uiLanguages": item.get("available_ui_languages", []),
        "deprecated": bool(item.get("deprecated")),
        "experimental": bool(item.get("experimental")),
        "origin": "crawler",
    }


def _ingest_items(
    items: list, owner_id: int, session: requests.Session, counts: dict[str, int], errors: list[str]
) -> None:
    with db.session_scope() as s:
        for item in items[:MAX_ITEMS_PER_URL]:
            record = normalize_record(item) if isinstance(item, dict) else None
            if record is None:
                errors.append("invalid item (missing name/title/description/url)")
                continue
            name = str(item["name"])
            if exists_upstream(session, name):
                errors.append(f"{name}: exists upstream on Toolhub — skipped (live API is source of truth)")
                continue
            existing = s.execute(
                select(ToolRecord).where(ToolRecord.tool_name == name, ToolRecord.user_id == owner_id)
            ).scalar_one_or_none()
            if existing is None:
                s.add(ToolRecord(tool_name=name, user_id=owner_id, record=record, modified_at=utcnow()))
                counts["added"] += 1
            else:
                existing.record = record
                existing.modified_at = utcnow()
                counts["updated"] += 1


def run_crawl() -> CrawlerRun:
    """One full crawl pass; records and returns a CrawlerRun row."""
    session = requests.Session()
    counts = {"added": 0, "updated": 0}
    errors: list[str] = []
    with db.session_scope() as s:
        targets = [(c.url, c.user_id) for c in s.execute(select(CrawlerUrl)).scalars()]
    for url, owner_id in targets:
        try:
            data = _fetch_json(session, url)
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")
            continue
        _ingest_items(data if isinstance(data, list) else [data], owner_id, session, counts, errors)
    run = CrawlerRun(
        started_at=utcnow(),
        ended_at=utcnow(),
        urls_count=len(targets),
        added=counts["added"],
        updated=counts["updated"],
        ok=not errors,
        errors=errors,
    )
    with db.session_scope() as s:
        s.add(run)
    return run


def main() -> int:
    """Jobs-framework entrypoint: configure the DB, crawl, report."""
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    run = run_crawl()
    sys.stdout.write(
        f"crawl: {run.urls_count} urls, +{run.added} added, ~{run.updated} updated, {len(run.errors)} errors\n"
    )
    return 0 if run.ok else 1


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
