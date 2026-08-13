# SPDX-License-Identifier: GPL-3.0-or-later
"""Server-side toolinfo crawler (Toolforge Jobs framework; see jobs.yaml).

Fetches every registered toolinfo.json URL (the union across users), validates
the records, and upserts them as locally-registered tools attributed to the
user who registered the URL. Per the resolved data architecture
(docs/PRODUCTION.md §0), a name that already exists upstream on Toolhub is
skipped: the live API stays that record's source of truth — we never store a
shadow copy of upstream data. That skip is a successful outcome, so it is
reported separately from `errors`, which alone decides the run verdict and the
exit code the job guard counts failures from.
"""

import json
import sys

import requests
from sqlalchemy import select

from backend import db, job_runner, outbound
from backend.author_claims import SignedToolinfoProvider
from backend.models import CrawlerRun, CrawlerUrl, ToolRecord, User, utcnow
from backend.sync import REVIEW_APPROVED, SOURCE_LOCAL, SYNC_ERROR, SYNC_EVOLVED_REAL

UPSTREAM_TOOL = "https://toolhub.wikimedia.org/api/tools/"
UA = "toolhub-evolved-crawler/1.0 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
TIMEOUT = 20  # upstream_state only; registered-URL fetches use outbound.STRICT_PUBLIC
MAX_ITEMS_PER_URL = 200
_CALLER = outbound.Caller(
    user_agent=UA,
    accept="application/json",
    scheme_error="only https toolinfo URLs are crawled",
)
HTTP_NOT_FOUND = 404
SIGNED_TOOLINFO_PROVIDER = SignedToolinfoProvider()

# What the official Toolhub told us about a name, and how we report the outcome.
UPSTREAM_PRESENT = "present"
UPSTREAM_ABSENT = "absent"
UPSTREAM_UNREACHABLE = "unreachable"
BUCKET_SKIPPED = "skipped"  # healthy no-op: leaves run.ok True, exit 0
BUCKET_ERROR = "error"  # fails the run, and counts toward the job guard's streak


def _fetch_json(session: requests.Session, url: str) -> object:
    """GET a registered toolinfo URL under the strict public-fetch policy.

    Registered URLs are user-supplied, so this must never become an SSRF probe of
    the Toolforge network. The guarantees — https only, non-public addresses
    refused, redirects refused, body capped — live in backend.outbound.
    """
    body = outbound.fetch_bounded(session, url, policy=outbound.STRICT_PUBLIC, caller=_CALLER)
    return json.loads(body.decode("utf-8"))


def upstream_state(session: requests.Session, name: str) -> str:
    """Ask the official Toolhub whether it already has this tool name.

    Three answers, not two: a confirmed hit, a confirmed miss, and "we could not
    ask". Only a confirmed miss may be ingested — that is what stops a Toolhub
    outage from making us shadow an upstream record — but the two non-miss cases
    are not equally healthy, so classify_upstream() reports them separately.
    """
    try:
        resp = session.get(f"{UPSTREAM_TOOL}{name}/", headers={"User-Agent": UA}, timeout=TIMEOUT)
    except requests.RequestException:
        return UPSTREAM_UNREACHABLE
    return UPSTREAM_ABSENT if resp.status_code == HTTP_NOT_FOUND else UPSTREAM_PRESENT


def classify_upstream(state: str, name: str) -> tuple[str, str] | None:
    """Decide how one upstream answer is reported: (bucket, message), or None to ingest.

    Return None only for UPSTREAM_ABSENT — the sole state where storing a local
    record is correct. For the other two, return BUCKET_SKIPPED for an outcome
    that should leave the run green, or BUCKET_ERROR for one that should fail the
    run and count toward the job guard's three-strike disable.

    TODO(christophe): UPSTREAM_UNREACHABLE is the judgement call. Treating it as
    BUCKET_SKIPPED keeps a Toolhub outage from disabling the crawler again, but
    an extended outage then reads as a permanently green, permanently idle job.
    Treating it as BUCKET_ERROR surfaces the outage loudly at the cost of the
    same disable behaviour we are fixing here — bounded, since an outage is
    transient where "exists upstream" was permanent. The interim default below
    is the conservative one; change it if you want the outage to shout.
    """
    if state == UPSTREAM_ABSENT:
        return None
    if state == UPSTREAM_PRESENT:
        return BUCKET_SKIPPED, f"{name}: exists upstream on Toolhub — skipped (live API is source of truth)"
    return BUCKET_SKIPPED, f"{name}: upstream check unavailable — skipped (never shadow an upstream record)"


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


def _ingest_items(  # noqa: PLR0913, PLR0917 - signed-toolinfo evidence needs the source URL plus crawl state.
    items: list,
    owner_id: int,
    toolinfo_url: str,
    session: requests.Session,
    counts: dict[str, int],
    errors: list[str],
    skipped: list[str],
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
            verdict = classify_upstream(upstream_state(session, name), name)
            if verdict is not None:
                bucket, message = verdict
                (errors if bucket == BUCKET_ERROR else skipped).append(message)
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
    skipped: list[str] = []
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
        _ingest_items(data if isinstance(data, list) else [data], owner_id, url, session, counts, errors, skipped)
        with db.session_scope() as s:
            row = s.get(CrawlerUrl, url_id)
            if row:
                failed = len(errors) != error_count  # skips leave the URL healthy
                row.last_checked_at = utcnow()
                row.last_status = SYNC_ERROR if failed else SYNC_EVOLVED_REAL
                row.last_error = errors[-1][:2000] if failed else None
    run = CrawlerRun(
        started_at=utcnow(),
        ended_at=utcnow(),
        urls_count=len(targets),
        added=counts["added"],
        updated=counts["updated"],
        ok=not errors,
        errors=errors,
        skipped=skipped,
        source=SOURCE_LOCAL,
        sync_status=SYNC_EVOLVED_REAL if not errors else SYNC_ERROR,
    )
    with db.session_scope() as s:
        s.add(run)
    return run


def main() -> int:
    """Jobs-framework entrypoint: configure the DB, crawl, report."""

    def body() -> None:
        run = run_crawl()
        sys.stdout.write(
            f"crawl: {run.urls_count} urls, +{run.added} added, ~{run.updated} updated, "
            f"{len(run.skipped)} skipped, {len(run.errors)} errors\n"
        )

    # Per backend.job_contract: the sweep completed. Unreachable feeds are
    # already durable observations on CrawlerRun and on each URL row, and this
    # job has so few registered URLs that one flaky feed used to exit non-zero
    # for the whole run -- which tripped the breaker for ten days in August.
    return job_runner.run_job("crawler", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
