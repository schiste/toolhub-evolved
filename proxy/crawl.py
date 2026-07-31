# SPDX-License-Identifier: GPL-3.0-or-later
"""Server-side toolinfo crawler (Toolforge Jobs framework; see jobs.yaml).

Fetches every registered toolinfo.json URL (the union across users), validates
the records, and upserts them as locally-registered tools attributed to the
user who registered the URL. Per the resolved data architecture
(docs/PRODUCTION.md §0), a name that already exists upstream on Toolhub is
skipped: the live API stays that record's source of truth — we never store a
shadow copy of upstream data.
"""

import json
import os
import sys

import requests
from sqlalchemy import select

from backend import DEFAULT_DB_URL, db, outbound
from backend.author_claims import SignedToolinfoProvider
from backend.models import CrawlerRun, CrawlerUrl, ToolRecord, User, utcnow
from backend.sync import REVIEW_APPROVED, SOURCE_LOCAL, SYNC_ERROR, SYNC_EVOLVED_REAL

UPSTREAM_TOOL = "https://toolhub.wikimedia.org/api/tools/"
UA = "toolhub-evolved-crawler/1.0 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
TIMEOUT = 20  # exists_upstream only; registered-URL fetches use outbound.STRICT_PUBLIC
MAX_ITEMS_PER_URL = 200
_CALLER = outbound.Caller(
    user_agent=UA,
    accept="application/json",
    scheme_error="only https toolinfo URLs are crawled",
)
HTTP_NOT_FOUND = 404
SIGNED_TOOLINFO_PROVIDER = SignedToolinfoProvider()


def _fetch_json(session: requests.Session, url: str) -> object:
    """GET a registered toolinfo URL under the strict public-fetch policy.

    Registered URLs are user-supplied, so this must never become an SSRF probe of
    the Toolforge network. The guarantees — https only, non-public addresses
    refused, redirects refused, body capped — live in backend.outbound.
    """
    body = outbound.fetch_bounded(session, url, policy=outbound.STRICT_PUBLIC, caller=_CALLER)
    return json.loads(body.decode("utf-8"))


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


def _ingest_items(  # noqa: PLR0913 - signed-toolinfo evidence needs the source URL plus crawl state.
    items: list,
    owner_id: int,
    toolinfo_url: str,
    session: requests.Session,
    counts: dict[str, int],
    errors: list[str],
) -> None:
    affected_names: set[str] = set()
    with db.session_scope() as s:
        owner = s.get(User, owner_id)
        for item in items[:MAX_ITEMS_PER_URL]:
            record = normalize_record(item) if isinstance(item, dict) else None
            if record is None:
                errors.append("invalid item (missing name/title/description/url)")
                continue
            name = str(item["name"])
            if owner is not None:
                SIGNED_TOOLINFO_PROVIDER.verify(s, owner, toolinfo=item, evidence_url=toolinfo_url)
                affected_names.add(name)
            if exists_upstream(session, name):
                errors.append(f"{name}: exists upstream on Toolhub — skipped (live API is source of truth)")
                continue
            existing = s.execute(
                select(ToolRecord).where(ToolRecord.tool_name == name, ToolRecord.user_id == owner_id)
            ).scalar_one_or_none()
            if existing is None:
                s.add(
                    ToolRecord(
                        tool_name=name,
                        user_id=owner_id,
                        created_by_user_id=owner_id,
                        record=record,
                        modified_at=utcnow(),
                        visibility="public",
                        source=SOURCE_LOCAL,
                        sync_status=SYNC_EVOLVED_REAL,
                        review_status=REVIEW_APPROVED,
                    )
                )
                counts["added"] += 1
            else:
                existing.record = record
                existing.modified_at = utcnow()
                existing.visibility = "public"
                existing.source = SOURCE_LOCAL
                existing.sync_status = SYNC_EVOLVED_REAL
                existing.review_status = REVIEW_APPROVED
                if existing.created_by_user_id is None:
                    existing.created_by_user_id = owner_id
                existing.last_error = None
                counts["updated"] += 1
    if affected_names:
        from backend.people_reconcile import enqueue_tool_names  # noqa: PLC0415 - avoid crawler startup cycles.

        enqueue_tool_names(affected_names, reason="toolinfo_ingestion")


def run_crawl() -> CrawlerRun:
    """One full crawl pass; records and returns a CrawlerRun row."""
    session = requests.Session()
    counts = {"added": 0, "updated": 0}
    errors: list[str] = []
    with db.session_scope() as s:
        targets = [(c.id, c.url, c.user_id) for c in s.execute(select(CrawlerUrl).where(CrawlerUrl.enabled)).scalars()]
    for url_id, url, owner_id in targets:
        error_count = len(errors)
        try:
            data = _fetch_json(session, url)
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")
            with db.session_scope() as s:
                row = s.get(CrawlerUrl, url_id)
                if row:
                    row.last_checked_at = utcnow()
                    row.last_status = SYNC_ERROR
                    row.last_error = str(exc)[:2000]
            continue
        _ingest_items(data if isinstance(data, list) else [data], owner_id, url, session, counts, errors)
        with db.session_scope() as s:
            row = s.get(CrawlerUrl, url_id)
            if row:
                row.last_checked_at = utcnow()
                row.last_status = SYNC_EVOLVED_REAL if len(errors) == error_count else SYNC_ERROR
                row.last_error = None if len(errors) == error_count else errors[-1][:2000]
    run = CrawlerRun(
        started_at=utcnow(),
        ended_at=utcnow(),
        urls_count=len(targets),
        added=counts["added"],
        updated=counts["updated"],
        ok=not errors,
        errors=errors,
        source=SOURCE_LOCAL,
        sync_status=SYNC_EVOLVED_REAL if not errors else SYNC_ERROR,
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
