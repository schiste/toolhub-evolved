# SPDX-License-Identifier: GPL-3.0-or-later
"""Background reachability validation for effective catalog URLs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from sqlalchemy import select

from backend import db, outbound
from backend.catalog_projection import URL_FIELDS
from backend.models import CatalogToolProjection, utcnow

MAX_CHECKS = 200
FRESH_FOR = timedelta(days=7)
# Rows per fetch for the candidate scan; see `_candidate_rows`.
STREAM_BATCH_SIZE = 500
CALLER = outbound.Caller(
    user_agent="toolhub-evolved/0.2 (https://toolhub-evolved.toolforge.org)",
    accept="*/*",
    scheme_error="catalog URL must be public HTTP or HTTPS",
)


def _text(value: Any) -> str:  # noqa: ANN401
    return str(value or "").strip()


def _parsed(value: Any) -> datetime | None:  # noqa: ANN401
    try:
        parsed = datetime.fromisoformat(_text(value).removesuffix("Z"))
    except ValueError:
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def _candidate_rows(limit: int) -> tuple[int, list[tuple[str, str, str]]]:
    """Count every URL due for a probe and return the first `limit` of them.

    Three columns, not the row, and streamed rather than materialized. The scan
    reads only the effective record and its recorded validation state, but a
    projection row also carries `provenance`, `source_timestamps` and
    `search_text`; selecting the entity dragged all of it in. Combined with a
    candidate pool that went from ~20,000 URLs to 82,911 when discovery opened
    up to every Wikimedia project, that OOM-killed this job on every hourly
    tick for a day. `yield_per` is what actually bounds it: the loop keeps only
    the small `(name, field, url)` tuples, so peak memory is a batch of rows
    rather than the whole table, whatever the catalogue grows to next.
    """
    now = utcnow()
    candidates = []
    with db.session_scope() as s:
        rows = s.execute(
            select(
                CatalogToolProjection.tool_name,
                CatalogToolProjection.effective_record,
                CatalogToolProjection.validation,
            )
            .order_by(CatalogToolProjection.tool_name)
            .execution_options(yield_per=STREAM_BATCH_SIZE)
        )
        for row in rows:
            record = row.effective_record if isinstance(row.effective_record, dict) else {}
            validation = row.validation if isinstance(row.validation, dict) else {}
            for field in sorted(URL_FIELDS):
                value = _text(record.get(field))
                if not value:
                    continue
                state = validation.get(field) if isinstance(validation.get(field), dict) else {}
                checked = _parsed(state.get("checkedAt"))
                if state.get("checkedValue") != value or checked is None or checked + FRESH_FOR <= now:
                    candidates.append((row.tool_name, field, value))
    return len(candidates), candidates[:limit]


def _record(tool_name: str, field: str, value: str, result: dict[str, Any]) -> None:
    with db.session_scope() as s:
        row = s.get(CatalogToolProjection, tool_name)
        if row is None or _text((row.effective_record or {}).get(field)) != value:
            return
        validation = dict(row.validation or {})
        state = dict(validation.get(field) or {})
        state.update(result)
        state["checkedValue"] = value
        state["checkedAt"] = utcnow().isoformat(timespec="seconds") + "Z"
        validation[field] = state
        row.validation = validation


def refresh_candidates(limit: int = MAX_CHECKS, *, session: requests.Session | None = None) -> dict[str, int]:
    bounded = max(1, min(MAX_CHECKS, int(limit or 1)))
    total, candidates = _candidate_rows(bounded)
    http = session or requests.Session()
    reachable = errors = 0
    for tool_name, field, value in candidates:
        try:
            response = outbound.probe_reachable(http, value, caller=CALLER)
            result = {
                "reachable": True,
                "statusCode": response.status_code,
                "contentType": response.content_type,
                "finalUrl": response.url,
                "lastError": "",
            }
            reachable += 1
        except (requests.RequestException, ValueError) as exc:
            result = {"reachable": False, "lastError": str(exc)[:1000]}
            errors += 1
        _record(tool_name, field, value, result)
    return {"candidates": total, "processed": len(candidates), "reachable": reachable, "errors": errors}
