# SPDX-License-Identifier: GPL-3.0-or-later
"""Background reachability validation for effective catalog URLs."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from sqlalchemy import select

from backend import db, outbound, run_budget
from backend.catalog_projection import URL_FIELDS
from backend.models import CatalogToolProjection, utcnow

# Distinct URLs probed per run, not rows written. 200 was set when the catalog
# was 4,508 tools; at 53,178 it stopped being a batch size and became a ceiling
# below the refresh rate. `FRESH_FOR` asks for the whole corpus every 7 days --
# about 58,000 distinct targets once `_probe_target` has folded the duplicates
# -- which is 345 an hour.
#
# What actually bounds a run is `DEFAULT_BUDGET`, not this. A count has to be
# guessed from a per-item cost nobody measures again: 500 targets was set from
# a guess, and the measured cost turned out to be 0.15s each, so the job spent
# 76 seconds of its hour and left the backlog climbing. `MAX_CHECKS` stays as
# the safety cap for the case the budget cannot catch -- targets that resolve
# instantly, and a loop that would otherwise probe until the table is
# exhausted -- and is set well above anything one budgeted run can reach.
MAX_CHECKS = 20_000
# Ten minutes of the hour between runs. The rest is left to the two dozen other
# jobs that share this database and to the hosts on the other end of the probes.
DEFAULT_BUDGET = 600
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


def _record(fields: list[tuple[str, str, str]], result: dict[str, Any]) -> int:
    """Write one probe's verdict against every field that named its target.

    One transaction for the whole target, not one per field. A wiki tool
    publishes the same page as `url` and as `repository`, so the common case is
    two writes that were two round trips to a database two dozen jobs share --
    and at the throughput this job now runs at, that difference is thousands of
    transactions an hour bought for nothing.
    """
    checked_at = utcnow().isoformat(timespec="seconds") + "Z"
    written = 0
    with db.session_scope() as s:
        for tool_name, field, value in fields:
            row = s.get(CatalogToolProjection, tool_name)
            if row is None or _text((row.effective_record or {}).get(field)) != value:
                continue
            validation = dict(row.validation or {})
            state = dict(validation.get(field) or {})
            state.update(result)
            state["checkedValue"] = value
            state["checkedAt"] = checked_at
            validation[field] = state
            row.validation = validation
            written += 1
    return written


def refresh_candidates(
    limit: int = MAX_CHECKS,
    *,
    session: requests.Session | None = None,
    budget: run_budget.Budget | None = None,
) -> dict[str, int]:
    """Probe each distinct target once and record the verdict on every field naming it.

    `candidates` and `processed` count targets, which is requests; `recorded`
    counts the validation states written from them. The two differ by exactly
    the duplication `_probe_target` folds, so the gap between them is the
    saving, visible in the job log rather than inferred from it.

    The run stops when `budget` is spent, which is what a scheduled run is
    really bounded by; `limit` is the safety cap. `spentSeconds` and `budgeted`
    go into the summary so the next reader can see which of the two ended the
    run, rather than having to infer it from a duration.
    """
    bounded = max(1, min(MAX_CHECKS, int(limit or 1)))
    clock = budget or run_budget.Budget(DEFAULT_BUDGET)
    total, targets = _candidate_rows(bounded)
    http = session or requests.Session()
    reachable = errors = recorded = processed = 0
    for target, fields in targets.items():
        if not clock.remains():
            break
        processed += 1
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
        recorded += _record(fields, result)
    return {
        "candidates": total,
        "processed": processed,
        "recorded": recorded,
        "reachable": reachable,
        "errors": errors,
        "spentSeconds": round(clock.spent(), 1),
        "budgeted": int(clock.seconds),
    }
