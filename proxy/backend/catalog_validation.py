# SPDX-License-Identifier: GPL-3.0-or-later
"""Background reachability validation for effective catalog URLs."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from sqlalchemy import select

from backend import db, outbound
from backend.catalog_projection import URL_FIELDS
from backend.models import CatalogToolProjection, utcnow

# Distinct URLs probed per run, not rows written. 200 was set when the catalog
# was 4,508 tools; at 53,178 it stopped being a batch size and became a ceiling
# below the refresh rate. `FRESH_FOR` asks for the whole corpus every 7 days --
# about 58,000 distinct targets once `_probe_target` has folded the duplicates
# -- which is 345 an hour. 200 an hour delivers a 22-day cycle and a candidate
# count that climbs until every URL is permanently overdue, which is what 91,202
# was. 500 leaves headroom for the catalog to keep growing without the cycle
# silently lengthening again.
MAX_CHECKS = 500
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


def _probe_target(url: str) -> str:
    """Return the URL to actually fetch to decide whether `url` resolves.

    Every wiki-lane tool publishes the same page twice: `url` is the page and
    `repository` is that page with `?action=raw`, both generated from one
    `UserScriptPage` by `userscript_toolinfo`. They are one resource -- they
    are served by one wiki, and they appear and disappear together -- so
    probing each separately spent two requests per tool to learn one fact, and
    with 48,670 wiki tools in the catalog that was the majority of this job's
    traffic.

    Only `action=raw` is folded, and only as a whole parameter. Any other query
    string may select a different resource, so it is left alone and probed on
    its own.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = parse_qsl(parts.query, keep_blank_values=True)
    kept = [pair for pair in query if pair != ("action", "raw")]
    if len(kept) == len(query):
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def _parsed(value: Any) -> datetime | None:  # noqa: ANN401
    try:
        parsed = datetime.fromisoformat(_text(value).removesuffix("Z"))
    except ValueError:
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def _candidate_rows(limit: int) -> tuple[int, dict[str, list[tuple[str, str, str]]]]:
    """Group every URL due for a probe by target, and return the first `limit` targets.

    Three columns, not the row, and streamed rather than materialized. The scan
    reads only the effective record and its recorded validation state, but a
    projection row also carries `provenance`, `source_timestamps` and
    `search_text`; selecting the entity dragged all of it in. Combined with a
    candidate pool that went from ~20,000 URLs to 82,911 when discovery opened
    up to every Wikimedia project, that OOM-killed this job on every hourly
    tick for a day. `yield_per` is what actually bounds it: the loop keeps only
    the small `(name, field, url)` tuples, so peak memory is a batch of rows
    rather than the whole table, whatever the catalogue grows to next.

    The unit returned is a target rather than a row, because `_probe_target`
    folds the wiki lane's `url` and `repository` onto one page and the limit
    that matters is how many requests the run makes -- not how many validation
    states it writes from them.
    """
    now = utcnow()
    due: defaultdict[str, list[tuple[str, str, str]]] = defaultdict(list)
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
                    due[_probe_target(value)].append((row.tool_name, field, value))
    targets = sorted(due)
    return len(targets), {target: due[target] for target in targets[:limit]}


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
    """Probe each distinct target once and record the verdict on every field naming it.

    `candidates` and `processed` count targets, which is requests; `recorded`
    counts the validation states written from them. The two differ by exactly
    the duplication `_probe_target` folds, so the gap between them is the
    saving, visible in the job log rather than inferred from it.
    """
    bounded = max(1, min(MAX_CHECKS, int(limit or 1)))
    total, targets = _candidate_rows(bounded)
    http = session or requests.Session()
    reachable = errors = recorded = 0
    for target, fields in targets.items():
        try:
            response = outbound.probe_reachable(http, target, caller=CALLER)
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
        for tool_name, field, value in fields:
            _record(tool_name, field, value, result)
            recorded += 1
    return {
        "candidates": total,
        "processed": len(targets),
        "recorded": recorded,
        "reachable": reachable,
        "errors": errors,
    }
