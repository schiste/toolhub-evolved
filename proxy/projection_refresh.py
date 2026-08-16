# SPDX-License-Identifier: GPL-3.0-or-later
"""Refresh last-good public projections outside the code deployment path."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import account_sync
import catalog_sync
import toolforge_account_sync
from backend import (
    catalog_statistics,
    db,
    identity_graph,
    job_runner,
    people_policy,
    people_reconcile,
    projection_policy,
    source_attestations,
)
from backend.models import (
    ApiCacheMeta,
    ToolCatalogSyncState,
    ToolforgeAccountSyncState,
    ToolhubAccountSyncState,
    utcnow,
)

if TYPE_CHECKING:
    from collections.abc import Callable

RUN_META_KEY = "projection_refresh_last_run"
IDENTITY_META_KEY = "identity_projection_input_v2"
IDENTITY_RULES_VERSION = projection_policy.module_fingerprint(
    identity_graph,
    people_policy,
    people_reconcile,
    source_attestations,
    namespace="identity-publication-policy-v1",
)
DEFAULT_MAX_AGE_SECONDS = 21_600
EARLIEST_IDENTITY_CHANGE = datetime(1970, 1, 1)  # noqa: DTZ001 - database timestamps are intentionally naive UTC


class ProjectionRefreshDeferredError(RuntimeError):
    """Raised when another worker owns one required input projection."""


def _iso(value: Any) -> str | None:  # noqa: ANN401 - datetime helper
    return value.isoformat(timespec="seconds") + "Z" if value is not None else None


def _persist(payload: dict[str, Any]) -> None:
    with db.session_scope() as session:
        row = session.get(ApiCacheMeta, RUN_META_KEY)
        if row is None:
            row = ApiCacheMeta(key=RUN_META_KEY, value="")
            session.add(row)
        row.value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        row.updated_at = utcnow()


def _fresh(completed_at: Any, cutoff: Any, status: str | None) -> bool:  # noqa: ANN401
    return completed_at is not None and completed_at >= cutoff and status == "idle"


def _sync_plan(max_age_seconds: int, *, force: bool) -> dict[str, bool]:
    if force:
        return {"toolhubAccounts": True, "toolforgeAccounts": True, "catalog": True}
    cutoff = utcnow() - timedelta(seconds=max(0, max_age_seconds))
    with db.session_scope() as session:
        toolhub = session.get(ToolhubAccountSyncState, account_sync.STATE_KEY)
        toolforge = session.get(ToolforgeAccountSyncState, toolforge_account_sync.STATE_KEY)
        catalog = session.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        return {
            "toolhubAccounts": not (toolhub and _fresh(toolhub.last_completed_at, cutoff, toolhub.status)),
            "toolforgeAccounts": not (toolforge and _fresh(toolforge.last_completed_at, cutoff, toolforge.status)),
            "catalog": not (catalog and _fresh(catalog.last_completed_at, cutoff, catalog.status)),
        }


def _run_catalog_sync() -> dict[str, Any]:
    """Share the catalog writer lock with scheduled sync and integrity jobs."""
    with db.advisory_lock("toolhub-evolved:catalog-sync") as acquired:
        if not acquired:
            return {"status": "locked", "completed": False}
        return catalog_sync.run()


def _parallel_sync(plan: dict[str, bool]) -> dict[str, dict[str, Any]]:
    tasks: dict[str, Callable[[], dict[str, Any]]] = {
        "toolhubAccounts": account_sync.run_complete,
        "toolforgeAccounts": toolforge_account_sync.run,
        # Normal projection publication must never turn a stale input marker
        # into a catalog-wide download. The incremental synchronizer consumes
        # recent changes and advances the rolling reconciliation cursor; the
        # separately scheduled integrity job owns complete snapshots.
        "catalog": _run_catalog_sync,
    }
    results: dict[str, dict[str, Any]] = {
        name: {"status": "fresh", "cacheHit": True} for name, should_run in plan.items() if not should_run
    }
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="projection-sync") as executor:
        futures = {executor.submit(tasks[name]): name for name, should_run in plan.items() if should_run}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = {**future.result(), "cacheHit": False}
    locked = [name for name, result in results.items() if result.get("status") == "locked"]
    if locked:
        raise ProjectionRefreshDeferredError("projection already refreshing: " + ", ".join(sorted(locked)))
    return results


def _identity_fingerprint() -> str:
    with db.session_scope() as session:
        return f"{IDENTITY_RULES_VERSION}:{identity_graph.input_fingerprint(session)}"


def _identity_marker() -> ApiCacheMeta | None:
    with db.session_scope() as session:
        return session.get(ApiCacheMeta, IDENTITY_META_KEY)


def _identity_is_current(fingerprint: str, *, force: bool) -> bool:
    if force:
        return False
    with db.session_scope() as session:
        row = session.get(ApiCacheMeta, IDENTITY_META_KEY)
        return row is not None and row.value == fingerprint


def _publish_identity_projection(fingerprint: str, *, changed_since: datetime) -> dict[str, Any]:
    with db.advisory_lock("toolhub-evolved:people-reconcile") as acquired:
        if not acquired:
            return {"status": "locked", "published": False}
        with db.session_scope() as session:
            people = people_reconcile.run(
                session,
                mode=people_reconcile.MODE_APPLY,
                # Network-backed unresolved-label discovery has its own hourly
                # bounded job. Projection publication uses stable local inputs
                # only, keeping this transaction deterministic and short.
                discover_candidates=False,
                candidate_label_limit=people_reconcile.DEFAULT_CANDIDATE_LABEL_LIMIT,
                rebuild_tools=False,
                sync_accounts=True,
                refresh_sources=True,
                source_changes_since=changed_since,
            )
            marker = session.get(ApiCacheMeta, IDENTITY_META_KEY)
            if marker is None:
                marker = ApiCacheMeta(key=IDENTITY_META_KEY, value=fingerprint)
                session.add(marker)
            else:
                marker.value = fingerprint
                marker.updated_at = utcnow()
    return {"status": "published", "published": True, "people": people}


def _timed(call: Callable[[], Any]) -> tuple[Any, int]:
    started = time.monotonic()
    return call(), round((time.monotonic() - started) * 1000)


def run(
    *, force: bool = False, full_sources: bool = False, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS
) -> dict[str, Any]:
    """Refresh inputs concurrently, then atomically publish one derived graph."""
    started_at = utcnow()
    report: dict[str, Any] = {
        "status": "running",
        "startedAt": _iso(started_at),
        "failurePhase": None,
        "stages": {},
    }
    _persist(report)
    try:
        report["failurePhase"] = "parallel-sync"
        plan = _sync_plan(max_age_seconds, force=force)
        sync, duration = _timed(lambda: _parallel_sync(plan))
        report["stages"]["parallelSync"] = {"durationMs": duration, "plan": plan, "results": sync}
        _persist(report)

        report["failurePhase"] = "canonical-retirements"
        retirements, duration = _timed(lambda: people_reconcile.drain_queue(reason="canonical_retired"))
        report["stages"]["retirements"] = {"durationMs": duration, "metrics": retirements}

        report["failurePhase"] = "identity-publication"
        fingerprint = _identity_fingerprint()
        identity_marker = _identity_marker()
        changed_since = identity_marker.updated_at if identity_marker is not None else EARLIEST_IDENTITY_CHANGE
        if _identity_is_current(fingerprint, force=force):
            identity: dict[str, Any] = {"status": "fresh", "published": False, "cacheHit": True}
            duration = 0
        else:
            identity, duration = _timed(lambda: _publish_identity_projection(fingerprint, changed_since=changed_since))
            identity["cacheHit"] = False
        report["stages"]["identityProjection"] = {"durationMs": duration, "metrics": identity}

        if full_sources:
            report["failurePhase"] = "full-source-audit"
            sources, duration = _timed(source_attestations.refresh_full_batched)
            report["stages"]["fullSourceAudit"] = {"durationMs": duration, "metrics": sources}

        report["failurePhase"] = "statistics"
        statistics, duration = _timed(lambda: catalog_statistics.snapshot(force=True))
        report["stages"]["statistics"] = {
            "durationMs": duration,
            "metrics": {"generatedAt": statistics["generatedAt"], "totalTools": statistics["catalog"]["totalTools"]},
        }
        report["status"] = "completed"
        report["failurePhase"] = None
    except ProjectionRefreshDeferredError as error:
        # Another refresh owns one or more complete input generations. This is
        # the same healthy overlap semantics as every other advisory-locked
        # worker: preserve the reason for operators, then let the owner finish.
        report["status"] = "deferred"
        report["failurePhase"] = None
        report["reason"] = str(error)[:2000]
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)[:2000]
        raise
    finally:
        report["completedAt"] = _iso(utcnow())
        report["durationMs"] = round((utcnow() - started_at).total_seconds() * 1000)
        _persist(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="ignore projection freshness")
    parser.add_argument("--full-sources", action="store_true", help="run the periodic complete source audit")
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=int(os.environ.get("PROJECTION_MAX_AGE_SECONDS", DEFAULT_MAX_AGE_SECONDS)),
    )
    args = parser.parse_args(argv)
    job_runner.configure()
    report = run(force=args.force, full_sources=args.full_sources, max_age_seconds=args.max_age_seconds)
    sys.stdout.write("projection-refresh: " + json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
